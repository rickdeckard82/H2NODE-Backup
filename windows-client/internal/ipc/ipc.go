// Package ipc liga a interface (um processo por usuário logado) ao serviço (SYSTEM)
// por named pipes locais, com HTTP/JSON por cima.
//
//   - UserPipe: usuários interativos — estado, "fazer backup agora", cancelar, log.
//   - AdminPipe: só Administradores (processo elevado) e SYSTEM — muda a configuração
//     (pastas, servidor/token, agendamento). Sem elevação o Windows recusa a conexão.
//
// Os dois negam acesso pela rede (SMB): só processos desta máquina.
package ipc

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"syscall"
	"time"

	"github.com/Microsoft/go-winio"
)

const (
	UserPipe  = `\\.\pipe\PulseBackup`
	AdminPipe = `\\.\pipe\PulseBackupAdmin`

	// D:P = DACL protegida. NU (logon de rede) negado; SY e BA total; IU (interativo) lê/escreve.
	UserSDDL  = "D:P(D;;GA;;;NU)(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)"
	AdminSDDL = "D:P(D;;GA;;;NU)(A;;GA;;;SY)(A;;GA;;;BA)"
)

var (
	ErrServiceDown  = errors.New("o serviço Pulse Backup não está rodando")
	ErrAccessDenied = errors.New("é preciso abrir o Pulse Backup como administrador para alterar a configuração")
)

// Listen abre um pipe com o descritor de segurança dado.
func Listen(name, sddl string) (net.Listener, error) {
	return winio.ListenPipe(name, &winio.PipeConfig{SecurityDescriptor: sddl, InputBufferSize: 64 << 10, OutputBufferSize: 64 << 10})
}

// Client fala com um dos pipes.
type Client struct {
	pipe string
	http *http.Client
}

func NewClient(pipe string) *Client {
	return &Client{pipe: pipe, http: &http.Client{
		Timeout: 2 * time.Minute, // "testar conexão" espera o servidor remoto
		Transport: &http.Transport{
			DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
				c, err := winio.DialPipeContext(ctx, pipe)
				if err != nil {
					return nil, classify(err)
				}
				return c, nil
			},
			MaxIdleConns:    2,
			IdleConnTimeout: 30 * time.Second,
		},
	}}
}

func classify(err error) error {
	switch {
	case errors.Is(err, os.ErrNotExist), errors.Is(err, syscall.ERROR_FILE_NOT_FOUND):
		return ErrServiceDown
	case errors.Is(err, os.ErrPermission), errors.Is(err, syscall.ERROR_ACCESS_DENIED):
		return ErrAccessDenied
	}
	return err
}

// Call faz um pedido JSON. Erros do serviço chegam como {"error": "..."}.
func (c *Client) Call(ctx context.Context, method, path string, in, out any) error {
	var body io.Reader
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return err
		}
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, "http://pulse-backup"+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		switch {
		case errors.Is(err, ErrServiceDown):
			return ErrServiceDown
		case errors.Is(err, ErrAccessDenied):
			return ErrAccessDenied
		}
		return fmt.Errorf("serviço: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode >= 300 {
		var e struct {
			Error string `json:"error"`
		}
		if json.Unmarshal(data, &e) == nil && e.Error != "" {
			return errors.New(e.Error)
		}
		return fmt.Errorf("serviço respondeu HTTP %d", resp.StatusCode)
	}
	if out == nil {
		return nil
	}
	if s, ok := out.(*string); ok {
		*s = string(data)
		return nil
	}
	return json.Unmarshal(data, out)
}

// IsDenied/IsDown para a interface decidir o que mostrar.
func IsDenied(err error) bool { return errors.Is(err, ErrAccessDenied) }
func IsDown(err error) bool   { return errors.Is(err, ErrServiceDown) }
