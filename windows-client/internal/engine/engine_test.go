package engine

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ProtonMail/go-crypto/openpgp"
	"github.com/ProtonMail/go-crypto/openpgp/armor"
	"github.com/ProtonMail/go-crypto/openpgp/packet"

	"pulse-backup/windows-client/internal/api"
)

// fakeServer imita /api/agent/v1: execuções, pedaços com offset e manifesto.
type fakeServer struct {
	mu        sync.Mutex
	files     map[string][]byte // run/name -> bytes
	manifest  map[string][]byte
	runs      int
	failEvery int // devolve 502 a cada N PUTs de pedaço (rede instável)
	puts      int
}

func (f *fakeServer) handler(t *testing.T) http.Handler {
	fileRe := regexp.MustCompile(`^/api/agent/v1/runs/([^/]+)/files/([^/]+)$`)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer pbu_teste" {
			w.WriteHeader(401)
			return
		}
		f.mu.Lock()
		defer f.mu.Unlock()
		switch {
		case r.Method == "POST" && r.URL.Path == "/api/agent/v1/runs":
			f.runs++
			w.WriteHeader(201)
			fmt.Fprintf(w, `{"run_name":"20261018T120000Z-%06x"}`, f.runs)
		case strings.HasSuffix(r.URL.Path, "/manifest") && r.Method == "PUT":
			body, _ := io.ReadAll(r.Body)
			f.manifest[strings.Split(r.URL.Path, "/")[5]] = body
			fmt.Fprint(w, `{"ok":true}`)
		case fileRe.MatchString(r.URL.Path):
			m := fileRe.FindStringSubmatch(r.URL.Path)
			key := m[1] + "/" + m[2]
			if r.Method == "GET" {
				fmt.Fprintf(w, `{"size":%d}`, len(f.files[key]))
				return
			}
			off, _ := strconv.Atoi(r.URL.Query().Get("offset"))
			body, _ := io.ReadAll(r.Body)
			f.puts++
			if off != len(f.files[key]) {
				w.WriteHeader(409)
				fmt.Fprint(w, `{"detail":"offset"}`)
				return
			}
			f.files[key] = append(f.files[key], body...)
			if f.failEvery > 0 && f.puts%f.failEvery == 0 {
				// gravou, mas a resposta "se perdeu": o cliente precisa retomar pelo tamanho
				w.WriteHeader(502)
				return
			}
			fmt.Fprintf(w, `{"size":%d}`, len(f.files[key]))
		default:
			t.Errorf("rota inesperada %s %s", r.Method, r.URL.Path)
			w.WriteHeader(404)
		}
	})
}

func testKey(t *testing.T) (*openpgp.Entity, string) {
	t.Helper()
	e, err := openpgp.NewEntity("Pulse Backup teste", "", "t@example.com", &packet.Config{RSABits: 2048, Algorithm: packet.PubKeyAlgoRSA})
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	w, _ := armor.Encode(&buf, openpgp.PublicKeyType, nil)
	if err := e.Serialize(w); err != nil {
		t.Fatal(err)
	}
	w.Close()
	return e, buf.String()
}

func decrypt(t *testing.T, key *openpgp.Entity, data []byte) []byte {
	t.Helper()
	md, err := openpgp.ReadMessage(bytes.NewReader(data), openpgp.EntityList{key}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	out, err := io.ReadAll(md.UnverifiedBody)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func TestRunEndToEnd(t *testing.T) {
	key, armored := testKey(t)
	rcpt, err := ParsePublicKey(armored)
	if err != nil {
		t.Fatal(err)
	}

	src := t.TempDir()
	docs := filepath.Join(src, "Documentos")
	os.MkdirAll(filepath.Join(docs, "Sub pasta"), 0o755)
	big := bytes.Repeat([]byte("dados do financeiro "), 400_000) // ~8 MB: vários pedaços
	os.WriteFile(filepath.Join(docs, "relatório.txt"), []byte("olá"), 0o644)
	os.WriteFile(filepath.Join(docs, "Sub pasta", "grande.bin"), big, 0o644)
	os.WriteFile(filepath.Join(docs, "~$temp.docx"), []byte("lixo"), 0o644)
	single := filepath.Join(src, "planilha.xlsx")
	os.WriteFile(single, []byte("PK planilha"), 0o644)

	fs := &fakeServer{files: map[string][]byte{}, manifest: map[string][]byte{}, failEvery: 3}
	srv := httptest.NewServer(fs.handler(t))
	defer srv.Close()
	cl, err := api.New(srv.URL, "pbu_teste", "teste")
	if err != nil {
		t.Fatal(err)
	}
	cl.Backoff = func(int) time.Duration { return time.Millisecond }
	chunkSize = 1 << 20 // 1 MiB: força várias partes e retomadas

	work := t.TempDir()
	res := Run(context.Background(), cl, Options{
		ClientID: "pc-financeiro", Recipient: rcpt, WorkDir: work, Version: "win-test",
		Hostname: "PC", OSInfo: "Windows 11",
		Items:    []Item{{Path: docs, IsDir: true}, {Path: single}, {Path: filepath.Join(src, "sumiu")}},
		Excludes: []string{"~$*"},
	}, nil, t.Logf)

	if res.Status != "partial" { // o item que sumiu falha; os outros vão
		t.Fatalf("status %q, erros %v", res.Status, res.Errors)
	}
	var m Manifest
	if err := json.Unmarshal(fs.manifest[res.RunName], &m); err != nil {
		t.Fatal(err)
	}
	if m.Format != "pulse-backup/1" || m.ClientID != "pc-financeiro" || m.Status != "partial" || len(m.Components) != 3 {
		t.Fatalf("manifesto inesperado: %+v", m)
	}
	if m.EncryptionFingerprint != rcpt.Fingerprint {
		t.Fatalf("fingerprint %s", m.EncryptionFingerprint)
	}

	// pasta: tar.gz cifrado, sha do cifrado e do conteúdo conferem, exclusão aplicada
	c := m.Components[0]
	enc := fs.files[res.RunName+"/"+c.File]
	if c.Kind != "files" || c.Status != "ok" || int64(len(enc)) != c.Size || hexsha(enc) != c.SHA256 {
		t.Fatalf("componente pasta inconsistente: %+v (recebido %d bytes)", c, len(enc))
	}
	plain := decrypt(t, key, enc)
	if hexsha(plain) != c.PlainSHA256 || int64(len(plain)) != c.PlainSize {
		t.Fatal("plain_sha256/plain_size não conferem")
	}
	names := map[string][]byte{}
	gz, err := gzip.NewReader(bytes.NewReader(plain))
	if err != nil {
		t.Fatal(err)
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		b, _ := io.ReadAll(tr)
		names[h.Name] = b
	}
	if string(names["Documentos/relatório.txt"]) != "olá" || !bytes.Equal(names["Documentos/Sub pasta/grande.bin"], big) {
		t.Fatalf("conteúdo do tar errado: %v", keys(names))
	}
	if _, ok := names["Documentos/~$temp.docx"]; ok {
		t.Fatal("exclusão não aplicada")
	}

	// arquivo: cifrado como está
	f := m.Components[1]
	if f.Kind != "file" || string(decrypt(t, key, fs.files[res.RunName+"/"+f.File])) != "PK planilha" {
		t.Fatalf("componente arquivo errado: %+v", f)
	}
	if m.Components[2].Status != "failed" || m.Components[2].File != "" {
		t.Fatalf("item inexistente deveria falhar sem arquivo: %+v", m.Components[2])
	}
	// nada fica na pasta de trabalho
	if left, _ := os.ReadDir(work); len(left) != 0 {
		t.Fatalf("sobrou na pasta de trabalho: %v", left)
	}
}

func TestCancelClosesRunAsFailed(t *testing.T) {
	_, armored := testKey(t)
	rcpt, _ := ParsePublicKey(armored)
	fs := &fakeServer{files: map[string][]byte{}, manifest: map[string][]byte{}}
	srv := httptest.NewServer(fs.handler(t))
	defer srv.Close()
	cl, _ := api.New(srv.URL, "pbu_teste", "teste")
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	res := Run(ctx, cl, Options{ClientID: "x", Recipient: rcpt, WorkDir: t.TempDir(),
		Items: []Item{{Path: t.TempDir(), IsDir: true}}}, nil, nil)
	if res.Status == "success" {
		t.Fatal("cancelado não pode dar sucesso")
	}
}

func hexsha(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func keys(m map[string][]byte) []string {
	var out []string
	for k := range m {
		out = append(out, k)
	}
	return out
}
