//go:build windows

package ipc

import (
	"context"
	"os"
	"strconv"
	"testing"
	"time"

	"github.com/Microsoft/go-winio"
)

func elevated() bool {
	f, err := os.Open(`\\.\PHYSICALDRIVE0`)
	if err == nil {
		f.Close()
		return true
	}
	return false
}

// O pipe de administrador recusa um processo sem elevação. (Conecta antes do Accept:
// um processo sem elevação nem conseguiria criar as instâncias seguintes do pipe —
// no serviço quem cria é o SYSTEM.)
func TestAdminPipeRefusesNonElevated(t *testing.T) {
	if elevated() {
		t.Skip("processo elevado")
	}
	name := AdminPipe + "Test" + strconv.FormatInt(time.Now().UnixNano(), 36)
	l, err := Listen(name, AdminSDDL)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, err = winio.DialPipeContext(ctx, name)
	if classify(err) != ErrAccessDenied {
		t.Fatalf("esperava acesso negado, veio %v", err)
	}
}

func TestMissingPipeIsServiceDown(t *testing.T) {
	err := NewClient(UserPipe+"NaoExiste").Call(context.Background(), "GET", "/state", nil, nil)
	if !IsDown(err) {
		t.Fatalf("esperava ErrServiceDown, veio %v", err)
	}
}
