// Package api fala com o Pulse Backup pelo envio HTTPS (/api/agent/v1).
//
// Modelo do servidor: só cria execuções, acrescenta bytes a arquivos .gpg e fecha a
// execução com o manifest.json. Nada é lido de volta além do tamanho já recebido de
// um arquivo, usado para retomar envios interrompidos.
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Hello é a resposta de /hello: quem é o cliente e a chave pública para cifrar.
type Hello struct {
	ClientID             string `json:"client_id"`
	ClientName           string `json:"client_name"`
	PublicKey            string `json:"public_key"`
	PublicKeyFingerprint string `json:"public_key_fingerprint"`
	ChunkMax             int64  `json:"chunk_max"`
}

// Error é um erro devolvido pelo servidor (com a mensagem "detail" do FastAPI).
type Error struct {
	Status int
	Detail string
}

func (e *Error) Error() string {
	if e.Detail == "" {
		return fmt.Sprintf("servidor respondeu HTTP %d", e.Status)
	}
	return fmt.Sprintf("servidor respondeu HTTP %d: %s", e.Status, e.Detail)
}

// Client é seguro para uso concorrente.
type Client struct {
	base    string
	token   string
	http    *http.Client
	agent   string
	retries int
	// espera entre tentativas (exposto para os testes)
	Backoff func(attempt int) time.Duration
}

// New valida a URL (só https, exceto localhost para testes) e prepara o cliente.
func New(serverURL, token, userAgent string) (*Client, error) {
	u, err := url.Parse(strings.TrimRight(strings.TrimSpace(serverURL), "/"))
	if err != nil || u.Host == "" {
		return nil, fmt.Errorf("endereço do servidor inválido: %q", serverURL)
	}
	local := strings.HasPrefix(u.Hostname(), "127.") || u.Hostname() == "localhost"
	if u.Scheme != "https" && !(u.Scheme == "http" && local) {
		return nil, errors.New("o endereço do servidor precisa começar com https://")
	}
	if !strings.HasPrefix(token, "pbu_") {
		return nil, errors.New("token inválido (copie o token gerado em Servidores → Windows, no painel)")
	}
	return &Client{
		base:    u.String() + "/api/agent/v1",
		token:   token,
		agent:   userAgent,
		retries: 6,
		http: &http.Client{
			Timeout: 10 * time.Minute,
			Transport: &http.Transport{
				Proxy:                 http.ProxyFromEnvironment,
				TLSHandshakeTimeout:   20 * time.Second,
				ResponseHeaderTimeout: 10 * time.Minute,
				IdleConnTimeout:       90 * time.Second,
				MaxIdleConnsPerHost:   2,
			},
		},
		Backoff: func(attempt int) time.Duration {
			d := time.Duration(1<<attempt) * 2 * time.Second // 4s, 8s, 16s…
			if d > time.Minute {
				d = time.Minute
			}
			return d
		},
	}, nil
}

func (c *Client) do(ctx context.Context, method, path string, query url.Values, body io.Reader,
	size int64, contentType string, out any) error {
	u := c.base + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, u, body)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("User-Agent", c.agent)
	if body != nil {
		req.ContentLength = size
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 300 {
		var e struct {
			Detail any `json:"detail"`
		}
		_ = json.Unmarshal(data, &e)
		detail, _ := e.Detail.(string)
		if detail == "" && e.Detail != nil {
			detail = fmt.Sprint(e.Detail)
		}
		return &Error{Status: resp.StatusCode, Detail: detail}
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("resposta inesperada do servidor: %w", err)
		}
	}
	return nil
}

// retryable: falha de rede ou erro temporário do servidor/proxy.
func retryable(err error) bool {
	var e *Error
	if errors.As(err, &e) {
		return e.Status == 429 || e.Status == 502 || e.Status == 503 || e.Status == 504 || e.Status == 507
	}
	return !errors.Is(err, context.Canceled)
}

func (c *Client) withRetry(ctx context.Context, fn func() error) error {
	var err error
	for attempt := 1; ; attempt++ {
		if err = fn(); err == nil || !retryable(err) || attempt >= c.retries {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(c.Backoff(attempt)):
		}
	}
}

// SetRetries muda quantas vezes um pedido é tentado (1 = sem novas tentativas).
func (c *Client) SetRetries(n int) {
	if n >= 1 {
		c.retries = n
	}
}

// Hello confere o token e traz a chave pública e os limites do envio.
func (c *Client) Hello(ctx context.Context) (*Hello, error) {
	var h Hello
	err := c.withRetry(ctx, func() error { return c.do(ctx, http.MethodGet, "/hello", nil, nil, 0, "", &h) })
	if err != nil {
		return nil, err
	}
	if h.ChunkMax <= 0 {
		h.ChunkMax = 32 << 20
	}
	return &h, nil
}

// CreateRun abre uma execução e devolve o nome dela (gerado pelo servidor).
func (c *Client) CreateRun(ctx context.Context) (string, error) {
	var r struct {
		RunName string `json:"run_name"`
	}
	err := c.withRetry(ctx, func() error { return c.do(ctx, http.MethodPost, "/runs", nil, nil, 0, "", &r) })
	return r.RunName, err
}

func (c *Client) remoteSize(ctx context.Context, run, name string) (int64, error) {
	var r struct {
		Size int64 `json:"size"`
	}
	err := c.withRetry(ctx, func() error {
		return c.do(ctx, http.MethodGet, "/runs/"+url.PathEscape(run)+"/files/"+url.PathEscape(name), nil, nil, 0, "", &r)
	})
	return r.Size, err
}

// Upload envia o arquivo local `path` como `name` em pedaços de `chunk` bytes,
// retomando do que o servidor já tem (queda de rede, reinício do programa).
// progress recebe o total de bytes já no servidor.
func (c *Client) Upload(ctx context.Context, run, name, path string, chunk int64, progress func(sent, total int64)) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return err
	}
	total := st.Size()
	sent, err := c.remoteSize(ctx, run, name)
	if err != nil {
		return err
	}
	if sent > total {
		return fmt.Errorf("o servidor já tem %d bytes de %s, mais que o arquivo local (%d)", sent, name, total)
	}
	filePath := "/runs/" + url.PathEscape(run) + "/files/" + url.PathEscape(name)
	if total == 0 {
		// arquivo vazio: um PUT sem corpo cria o arquivo no servidor
		return c.withRetry(ctx, func() error {
			return c.do(ctx, http.MethodPut, filePath, url.Values{"offset": {"0"}}, bytes.NewReader(nil), 0,
				"application/octet-stream", nil)
		})
	}
	buf := make([]byte, chunk)
	failures := 0
	for sent < total {
		n, rerr := f.ReadAt(buf[:min(chunk, total-sent)], sent)
		if rerr != nil && !errors.Is(rerr, io.EOF) {
			return rerr
		}
		var r struct {
			Size int64 `json:"size"`
		}
		q := url.Values{"offset": {fmt.Sprint(sent)}}
		err := c.do(ctx, http.MethodPut, filePath, q, bytes.NewReader(buf[:n]), int64(n), "application/octet-stream", &r)
		var e *Error
		switch {
		case err == nil:
			sent = r.Size
			failures = 0
			if progress != nil {
				progress(sent, total)
			}
			continue
		case errors.As(err, &e) && e.Status == http.StatusConflict:
			// o pedaço anterior chegou mas a resposta se perdeu: pergunta onde parou
			if sent, err = c.remoteSize(ctx, run, name); err != nil {
				return err
			}
			continue
		case !retryable(err):
			return err
		}
		failures++
		if failures >= c.retries {
			return fmt.Errorf("envio de %s falhou %d vezes seguidas: %w", name, failures, err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(c.Backoff(failures)):
		}
		// depois de uma falha, a fonte da verdade é o servidor
		if s, serr := c.remoteSize(ctx, run, name); serr == nil {
			sent = s
		}
	}
	return nil
}

// CloseRun envia o manifest.json e fecha a execução (o worker a recebe em seguida).
func (c *Client) CloseRun(ctx context.Context, run string, manifest []byte) error {
	return c.withRetry(ctx, func() error {
		return c.do(ctx, http.MethodPut, "/runs/"+url.PathEscape(run)+"/manifest", nil,
			bytes.NewReader(manifest), int64(len(manifest)), "application/json", nil)
	})
}
