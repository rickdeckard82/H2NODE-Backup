// Package engine faz um backup: para cada item escolhido gera um .gpg (pasta =
// tar.gz cifrado; arquivo = cifrado como está), envia, apaga a cópia local e, no fim,
// fecha a execução com o manifest.json no formato do agente Linux (pulse-backup/1).
//
// Nada em claro vai para o disco: tar → gzip → OpenPGP é um pipeline em memória e só
// o resultado cifrado é gravado na pasta de trabalho, um item por vez (a pasta só
// precisa caber o maior item). Os arquivos de origem só são LIDOS.
package engine

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"time"

	"github.com/klauspost/pgzip"

	"pulse-backup/windows-client/internal/api"
)

// Item é uma pasta ou um arquivo escolhido para backup.
type Item struct {
	Path  string `json:"path"`
	IsDir bool   `json:"is_dir"`
	// Source: de onde ler, se não for Path (ex.: o mesmo caminho dentro da cópia de
	// sombra do VSS). O nome no backup continua sendo Path.
	Source string `json:"-"`
	// Note entra na mensagem do componente; NoteWarn o marca como aviso.
	Note     string `json:"-"`
	NoteWarn bool   `json:"-"`
}

func (it Item) src() string {
	if it.Source != "" {
		return it.Source
	}
	return it.Path
}

// Options de uma execução.
type Options struct {
	ClientID  string
	Recipient *Recipient
	Items     []Item
	Excludes  []string
	WorkDir   string
	Version   string // ex.: win-0.1.0 (vai no manifesto e aparece no painel)
	Hostname  string
	OSInfo    string
}

// Progress é enviado para a interface durante o backup.
type Progress struct {
	Phase     string `json:"phase"` // preparing | packing | uploading | closing | done
	Item      string `json:"item"`
	Index     int    `json:"index"` // 1..Count
	Count     int    `json:"count"`
	ItemBytes int64  `json:"item_bytes"` // lidos (packing) ou enviados (uploading)
	ItemTotal int64  `json:"item_total"` // total do envio do item (uploading)
}

// Component segue o ManifestComponent do servidor.
type Component struct {
	Kind        string `json:"kind"` // files | file
	Name        string `json:"name"`
	File        string `json:"file,omitempty"`
	Size        int64  `json:"size"`
	SHA256      string `json:"sha256,omitempty"`
	PlainSize   int64  `json:"plain_size"`
	PlainSHA256 string `json:"plain_sha256,omitempty"`
	Status      string `json:"status"` // ok | warning | failed
	Message     string `json:"message,omitempty"`
	DurationS   int64  `json:"duration_s"`
}

// Manifest segue o Manifest (pulse-backup/1) do servidor.
type Manifest struct {
	Format                string      `json:"format"`
	ClientID              string      `json:"client_id"`
	RunName               string      `json:"run_name"`
	AgentVersion          string      `json:"agent_version"`
	Hostname              string      `json:"hostname"`
	OS                    string      `json:"os"`
	StartedAt             time.Time   `json:"started_at"`
	FinishedAt            time.Time   `json:"finished_at"`
	Status                string      `json:"status"` // success | partial | failed
	EncryptionFingerprint string      `json:"encryption_fingerprint"`
	Components            []Component `json:"components"`
	Errors                []string    `json:"errors"`
}

// Result é o resumo guardado no histórico local.
type Result struct {
	RunName    string      `json:"run_name"`
	StartedAt  time.Time   `json:"started_at"`
	FinishedAt time.Time   `json:"finished_at"`
	Status     string      `json:"status"` // success | partial | failed | canceled
	Bytes      int64       `json:"bytes"`  // cifrados enviados
	Components []Component `json:"components"`
	Errors     []string    `json:"errors"`
}

var unsafeChars = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func safeName(s string) string {
	n := strings.Trim(unsafeChars.ReplaceAllString(s, "_"), "._-")
	if n == "" {
		n = "item"
	}
	if len(n) > 120 {
		n = n[:120]
	}
	return n
}

// countingHash conta e calcula o SHA-256 do que passa por ele.
type countingHash struct {
	h hash.Hash
	n int64
}

func newCountingHash() *countingHash { return &countingHash{h: sha256.New()} }

func (c *countingHash) Write(p []byte) (int, error) {
	c.n += int64(len(p))
	return c.h.Write(p)
}

func (c *countingHash) sum() string { return hex.EncodeToString(c.h.Sum(nil)) }

// Run executa o backup. Erros de um item viram componente "failed" e o backup segue;
// falha de envio (rede) interrompe os itens restantes.
// Retorno nomeado de propósito: o defer que marca FinishedAt precisa alterar o valor
// devolvido (com `return res` sem nome, a cópia sai antes do defer e a hora fica zerada).
func Run(ctx context.Context, cl *api.Client, o Options, report func(Progress), logf func(string, ...any)) (res Result) {
	res = Result{StartedAt: time.Now().UTC(), Status: "failed"}
	if report == nil {
		report = func(Progress) {}
	}
	if logf == nil {
		logf = func(string, ...any) {}
	}
	defer func() { res.FinishedAt = time.Now().UTC() }()

	report(Progress{Phase: "preparing", Count: len(o.Items)})
	if len(o.Items) == 0 {
		res.Errors = append(res.Errors, "nenhuma pasta ou arquivo selecionado")
		return res
	}
	run, err := cl.CreateRun(ctx)
	if err != nil {
		res.Errors = append(res.Errors, "não foi possível abrir a execução no servidor: "+err.Error())
		return res
	}
	res.RunName = run
	logf("início do backup %s (%d itens)", run, len(o.Items))

	work := filepath.Join(o.WorkDir, run)
	if err := os.MkdirAll(work, 0o700); err != nil {
		res.Errors = append(res.Errors, "pasta de trabalho: "+err.Error())
		return res
	}
	defer os.RemoveAll(work)

	stopped := false // falha de rede ou cancelamento: não processa os demais
	for i, it := range o.Items {
		if stopped {
			break
		}
		if ctx.Err() != nil {
			stopped = true
			break
		}
		comp, path := packItem(ctx, o, work, i, it, report)
		if comp.File == "" {
			res.Components = append(res.Components, comp)
			logf("%s %s: %s — %s", comp.Kind, comp.Name, comp.Status, comp.Message)
			continue
		}
		report(Progress{Phase: "uploading", Item: it.Path, Index: i + 1, Count: len(o.Items), ItemTotal: comp.Size})
		err := cl.Upload(ctx, run, comp.File, path, chunkSize, func(sent, total int64) {
			report(Progress{Phase: "uploading", Item: it.Path, Index: i + 1, Count: len(o.Items),
				ItemBytes: sent, ItemTotal: total})
		})
		os.Remove(path)
		if err != nil {
			stopped = true
			msg := "envio falhou; itens seguintes não foram processados: " + err.Error()
			if ctx.Err() != nil {
				msg = "cancelado durante o envio"
			}
			res.Components = append(res.Components, Component{Kind: comp.Kind, Name: comp.Name, Status: "failed", Message: msg})
			logf("%s %s: FALHOU — %s", comp.Kind, comp.Name, msg)
			continue
		}
		res.Bytes += comp.Size
		res.Components = append(res.Components, comp)
		logf("%s %s: %s (%d bytes cifrados) %s", comp.Kind, comp.Name, comp.Status, comp.Size, comp.Message)
	}

	anyOK, anyFailed := false, false
	for _, c := range res.Components {
		if c.Status == "failed" {
			anyFailed = true
			res.Errors = append(res.Errors, fmt.Sprintf("%s %s: %s", c.Kind, c.Name, c.Message))
		} else {
			anyOK = true
		}
	}
	if ctx.Err() != nil {
		res.Errors = append(res.Errors, "backup cancelado")
		anyFailed = true
	}
	status := "success"
	switch {
	case anyFailed && anyOK:
		status = "partial"
	case anyFailed || !anyOK:
		status = "failed"
	}

	// fecha a execução mesmo depois de falha/cancelamento: o painel mostra o que houve
	report(Progress{Phase: "closing", Count: len(o.Items)})
	m := Manifest{
		Format: "pulse-backup/1", ClientID: o.ClientID, RunName: run, AgentVersion: o.Version,
		Hostname: o.Hostname, OS: o.OSInfo, StartedAt: res.StartedAt, FinishedAt: time.Now().UTC(),
		Status: status, EncryptionFingerprint: o.Recipient.Fingerprint, Errors: res.Errors,
	}
	for _, c := range res.Components {
		c.Message = truncRunes(c.Message, 3900)
		m.Components = append(m.Components, c)
	}
	if m.Errors == nil {
		m.Errors = []string{}
	}
	data, _ := json.Marshal(m)
	closeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Minute)
	defer cancel()
	if err := cl.CloseRun(closeCtx, run, data); err != nil {
		res.Errors = append(res.Errors, "manifesto não foi enviado: "+err.Error())
		res.Status = "failed"
		logf("falha ao fechar a execução %s: %v", run, err)
		return res
	}
	res.Status = status
	if ctx.Err() != nil {
		res.Status = "canceled"
	}
	report(Progress{Phase: "done", Count: len(o.Items)})
	logf("backup %s enviado (status=%s, %d bytes)", run, status, res.Bytes)
	return res
}

// chunkSize é o tamanho dos pedaços do envio (o servidor aceita até 32 MiB).
var chunkSize int64 = 16 << 20

// SetChunkSize ajusta ao limite informado pelo servidor no /hello.
func SetChunkSize(max int64) {
	if max > 0 && max < chunkSize {
		chunkSize = max
	}
}

// packItem gera o .gpg de um item na pasta de trabalho. Sem File = item falhou.
func packItem(ctx context.Context, o Options, work string, i int, it Item, report func(Progress)) (Component, string) {
	t0 := time.Now()
	kind := "file"
	if it.IsDir {
		kind = "files"
	}
	comp := Component{Kind: kind, Name: truncRunes(it.Path, 255), Status: "failed"}
	info, err := os.Stat(it.src())
	switch {
	case err != nil:
		comp.Message = "não encontrado: " + err.Error()
		return comp, ""
	case it.IsDir != info.IsDir():
		comp.Message = "o caminho mudou de tipo (pasta/arquivo) desde que foi escolhido"
		return comp, ""
	}
	base := baseName(it.Path)
	file := fmt.Sprintf("%02d-%s-%s.gpg", i+1, kind, safeName(base))
	if it.IsDir {
		file = fmt.Sprintf("%02d-%s-%s.tar.gz.gpg", i+1, kind, safeName(base))
	}
	path := filepath.Join(work, file)
	out, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		comp.Message = "pasta de trabalho: " + err.Error()
		return comp, ""
	}
	enc := newCountingHash()
	plain := newCountingHash()
	fail := func(msg string) (Component, string) {
		out.Close()
		os.Remove(path)
		comp.Message = msg
		comp.DurationS = int64(time.Since(t0).Seconds())
		return comp, ""
	}
	encW, err := o.Recipient.Encrypt(io.MultiWriter(out, enc))
	if err != nil {
		return fail("falha ao preparar a cifra: " + err.Error())
	}
	var read atomic.Int64
	onBytes := func(n int64) {
		v := read.Add(n)
		report(Progress{Phase: "packing", Item: it.Path, Index: i + 1, Count: len(o.Items), ItemBytes: v})
	}
	// o hash "plain" é do que vai dentro da cifra (o .tar.gz ou o arquivo), como no agente Linux
	sink := io.MultiWriter(encW, plain)
	var warn []string
	if it.IsDir {
		gz := pgzip.NewWriter(sink)
		gzClosed := false
		defer func() {
			if !gzClosed {
				gz.Close() // encerra as goroutines do pgzip mesmo em caso de erro
			}
		}()
		tw := tar.NewWriter(gz)
		st, werr := writeTar(ctx, it.src(), base, o.Excludes, tw, onBytes)
		if werr != nil {
			return fail("erro lendo a pasta: " + werr.Error())
		}
		if err := tw.Close(); err != nil {
			return fail("tar: " + err.Error())
		}
		gzClosed = true
		if err := gz.Close(); err != nil {
			return fail("gzip: " + err.Error())
		}
		comp.Message = fmt.Sprintf("%d arquivos, %d pastas", st.Files, st.Dirs)
		if n := len(st.Skipped); n > 0 {
			warn = append(warn, fmt.Sprintf("%d não puderam ser lidos (em uso ou sem permissão): %s", n, sample(st.Skipped)))
		}
		if n := len(st.Partial); n > 0 {
			warn = append(warn, fmt.Sprintf("%d mudaram durante a leitura: %s", n, sample(st.Partial)))
		}
		if st.Files == 0 && len(st.Skipped) == 0 {
			warn = append(warn, "pasta vazia")
		}
	} else {
		f, err := os.Open(it.src())
		if err != nil {
			return fail("não foi possível ler (em uso por outro programa?): " + err.Error())
		}
		_, cerr := io.Copy(sink, &ctxReader{ctx, f, onBytes})
		f.Close()
		if cerr != nil {
			return fail("erro lendo o arquivo: " + cerr.Error())
		}
	}
	if err := encW.Close(); err != nil {
		return fail("falha ao cifrar: " + err.Error())
	}
	if err := out.Close(); err != nil {
		return fail("pasta de trabalho: " + err.Error())
	}
	if ctx.Err() != nil {
		return fail("cancelado")
	}
	comp.File = file
	comp.Size = enc.n
	comp.SHA256 = enc.sum()
	comp.PlainSize = plain.n
	comp.PlainSHA256 = plain.sum()
	comp.Status = "ok"
	if it.Note != "" {
		comp.Message = strings.TrimSpace(comp.Message + " — " + it.Note)
		if it.NoteWarn {
			comp.Status = "warning"
		}
	}
	if len(warn) > 0 {
		comp.Status = "warning"
		comp.Message = strings.TrimSpace(comp.Message + " — " + strings.Join(warn, "; "))
	}
	comp.DurationS = int64(time.Since(t0).Seconds())
	return comp, path
}

// baseName: "Documentos" para C:\Users\x\Documentos; "C" para a raiz C:\ (vira a pasta
// de topo do tar e parte do nome do .gpg).
func baseName(p string) string {
	b := filepath.Base(filepath.Clean(p))
	if b == `\` || b == "/" || b == "." || strings.HasSuffix(b, ":") {
		return strings.Trim(strings.ReplaceAll(filepath.VolumeName(p), ":", ""), `\/`)
	}
	return b
}

func truncRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

func sample(list []string) string {
	const max = 5
	s := strings.Join(list[:min(len(list), max)], "; ")
	if len(list) > max {
		s += fmt.Sprintf("; … e mais %d", len(list)-max)
	}
	return s
}

// ErrNoItems para a interface.
var ErrNoItems = errors.New("nenhuma pasta ou arquivo selecionado")
