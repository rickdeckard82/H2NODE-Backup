//go:build windows

package service

import (
	"bytes"
	"context"
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

	"h2node-backup/windows-client/internal/config"
	"h2node-backup/windows-client/internal/engine"
	"h2node-backup/windows-client/internal/ipc"
)

// servidor H2NODE falso: /hello, /runs, pedaços e manifesto
func fakeH2node(t *testing.T) (*httptest.Server, *sync.Map) {
	e, err := openpgp.NewEntity("t", "", "t@x", &packet.Config{RSABits: 2048, Algorithm: packet.PubKeyAlgoRSA})
	if err != nil {
		t.Fatal(err)
	}
	var pub bytes.Buffer
	w, _ := armor.Encode(&pub, openpgp.PublicKeyType, nil)
	e.Serialize(w)
	w.Close()
	fpr := strings.ToUpper(fmt.Sprintf("%X", e.PrimaryKey.Fingerprint))
	files := &sync.Map{}
	fileRe := regexp.MustCompile(`^/api/agent/v1/runs/([^/]+)/files/([^/]+)$`)
	var mu sync.Mutex
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer pbu_teste" {
			w.WriteHeader(401)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		switch {
		case r.URL.Path == "/api/agent/v1/hello":
			fmt.Fprintf(w, `{"client_id":"pc-teste","client_name":"PC Teste","public_key":%q,"public_key_fingerprint":%q,"chunk_max":33554432}`, pub.String(), fpr)
		case r.URL.Path == "/api/agent/v1/runs":
			w.WriteHeader(201)
			fmt.Fprint(w, `{"run_name":"20261018T120000Z-abcdef"}`)
		case strings.HasSuffix(r.URL.Path, "/manifest"):
			b, _ := io.ReadAll(r.Body)
			files.Store("manifest", string(b))
			fmt.Fprint(w, `{"ok":true}`)
		case fileRe.MatchString(r.URL.Path):
			key := fileRe.FindStringSubmatch(r.URL.Path)[2]
			cur, _ := files.Load(key)
			data, _ := cur.([]byte)
			if r.Method == "GET" {
				fmt.Fprintf(w, `{"size":%d}`, len(data))
				return
			}
			off, _ := strconv.Atoi(r.URL.Query().Get("offset"))
			if off != len(data) {
				w.WriteHeader(409)
				return
			}
			b, _ := io.ReadAll(r.Body)
			data = append(data, b...)
			files.Store(key, data)
			fmt.Fprintf(w, `{"size":%d}`, len(data))
		default:
			w.WriteHeader(404)
		}
	}))
	return srv, files
}

func serve(t *testing.T, core *Core, adminSDDL string) (*ipc.Client, *ipc.Client) {
	t.Helper()
	suffix := strconv.FormatInt(time.Now().UnixNano(), 36)
	userName, adminName := ipc.UserPipe+"Test"+suffix, ipc.AdminPipe+"Test"+suffix
	ul, err := ipc.Listen(userName, ipc.UserSDDL)
	if err != nil {
		t.Fatal(err)
	}
	al, err := ipc.Listen(adminName, adminSDDL)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go core.Serve(ctx, ul, al)
	return ipc.NewClient(userName), ipc.NewClient(adminName)
}

func TestUserPipeStateAndNoConfigRoutes(t *testing.T) {
	core, err := New(t.TempDir(), "test", "Windows")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(core.Close)
	user, _ := serve(t, core, ipc.UserSDDL)
	var st State
	if err := user.Call(context.Background(), "GET", "/state", nil, &st); err != nil {
		t.Fatalf("pipe de usuário deveria responder: %v", err)
	}
	if !st.UseVSS || st.Schedule.Mode != "daily" {
		t.Fatalf("padrões: %+v", st)
	}
	// o pipe de usuário não tem rotas de configuração
	if err := user.Call(context.Background(), "POST", "/vss", map[string]bool{"enabled": false}, nil); err == nil {
		t.Fatal("pipe de usuário aceitou mudar a configuração")
	}
}

func TestConfigureAndBackupThroughPipes(t *testing.T) {
	srv, files := fakeH2node(t)
	defer srv.Close()
	dir := t.TempDir()
	core, err := New(dir, "test", "Windows")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(core.Close)
	// nos testes o "admin" usa o SDDL de usuário (o processo não é elevado)
	user, admin := serve(t, core, ipc.UserSDDL)
	ctx := context.Background()

	var info ConnectInfo
	if err := admin.Call(ctx, "POST", "/connect/test", map[string]string{"url": "https://x.invalid", "token": "pbu_teste"}, &info); err == nil {
		t.Fatal("host inválido deveria falhar")
	}
	if err := admin.Call(ctx, "POST", "/connect/confirm", nil, nil); err == nil {
		t.Fatal("confirmar sem testar deveria falhar")
	}
	if err := admin.Call(ctx, "POST", "/connect/test", map[string]string{"url": srv.URL, "token": "pbu_teste"}, &info); err != nil {
		t.Fatal(err)
	}
	if info.ClientID != "pc-teste" || len(info.Fingerprint) != 40 {
		t.Fatalf("info %+v", info)
	}
	if err := admin.Call(ctx, "POST", "/connect/confirm", nil, nil); err != nil {
		t.Fatal(err)
	}

	src := filepath.Join(t.TempDir(), "Documentos")
	os.MkdirAll(src, 0o755)
	os.WriteFile(filepath.Join(src, "a.txt"), []byte("conteúdo"), 0o644)
	if err := admin.Call(ctx, "POST", "/items/add", []engine.Item{{Path: `Z:\naoexiste`, IsDir: true}}, nil); err == nil {
		t.Fatal("caminho inexistente deveria ser recusado")
	}
	if err := admin.Call(ctx, "POST", "/items/add", []engine.Item{{Path: src, IsDir: true}}, nil); err != nil {
		t.Fatal(err)
	}
	if err := admin.Call(ctx, "POST", "/vss", map[string]bool{"enabled": false}, nil); err != nil {
		t.Fatal(err)
	}
	if err := admin.Call(ctx, "POST", "/schedule", config.Schedule{Mode: "daily", Time: "99:00"}, nil); err == nil {
		t.Fatal("horário inválido aceito")
	}

	if err := user.Call(ctx, "POST", "/run", nil, nil); err != nil {
		t.Fatal(err)
	}
	var st State
	for i := 0; i < 100; i++ {
		user.Call(ctx, "GET", "/state", nil, &st)
		if !st.Running && len(st.History) > 0 {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if len(st.History) == 0 || st.History[0].Status != "success" {
		t.Fatalf("backup não concluiu: %+v", st.History)
	}
	if m, ok := files.Load("manifest"); !ok || !strings.Contains(m.(string), `"client_id":"pc-teste"`) {
		t.Fatalf("manifesto não chegou: %v", m)
	}
	// configuração persistida, com o token protegido (não em claro)
	raw, _ := os.ReadFile(filepath.Join(dir, "config.json"))
	if bytes.Contains(raw, []byte("pbu_teste")) || !bytes.Contains(raw, []byte("Documentos")) {
		t.Fatal("config.json com token em claro ou sem o item")
	}
	var log string
	user.Call(ctx, "GET", "/log", nil, &log)
	if !strings.Contains(log, "backup iniciado (manual)") {
		t.Fatalf("log sem a execução: %q", log)
	}
}
