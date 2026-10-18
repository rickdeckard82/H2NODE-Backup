//go:build windows

package engine

import (
	"archive/tar"
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"

	"pulse-backup/windows-client/internal/vss"
)

// A cópia de sombra é lida por \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\…. O
// mesmo formato funciona com o dispositivo do volume VIVO (\Device\HarddiskVolumeN),
// sem administrador: assim o caminho de leitura do VSS é testado em qualquer máquina.
func TestReadThroughDevicePath(t *testing.T) {
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "Pasta", "Sub"), 0o755)
	os.WriteFile(filepath.Join(dir, "Pasta", "a.txt"), []byte("aaa"), 0o644)
	os.WriteFile(filepath.Join(dir, "Pasta", "Sub", "b.txt"), []byte("bbbb"), 0o644)

	orig := filepath.Join(dir, "Pasta")
	vol := vss.VolumeOf(orig)
	dev, err := vss.VolumeDevice(vol)
	if err != nil {
		t.Skipf("sem dispositivo para %s: %v", vol, err)
	}
	set := &vss.Set{Snaps: map[string]vss.Snapshot{vol: {Volume: vol, ID: "{x}", Device: dev}}}
	src, ok := set.Translate(orig)
	if !ok || src[:4] != `\\?\` {
		t.Fatalf("tradução inesperada: %q", src)
	}
	t.Logf("lendo %s por %s", orig, src)

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	st, err := writeTar(context.Background(), src, "Pasta", nil, tw, nil)
	if err != nil {
		t.Fatal(err)
	}
	tw.Close()
	if st.Files != 2 || len(st.Skipped) != 0 {
		t.Fatalf("stats %+v", st)
	}
	got := map[string]string{}
	tr := tar.NewReader(&buf)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		b, _ := io.ReadAll(tr)
		got[h.Name] = string(b)
	}
	if got["Pasta/a.txt"] != "aaa" || got["Pasta/Sub/b.txt"] != "bbbb" {
		t.Fatalf("conteúdo: %v", got)
	}

	// arquivo avulso pelo mesmo caminho
	fsrc, _ := set.Translate(filepath.Join(orig, "a.txt"))
	if b, err := os.ReadFile(fsrc); err != nil || string(b) != "aaa" {
		t.Fatalf("leitura do arquivo pelo dispositivo: %q %v", b, err)
	}
}

func TestBaseName(t *testing.T) {
	cases := map[string]string{`C:\`: "C", `C:\Users\maria\Documents`: "Documents", `D:\Contab\2026\`: "2026", `\\srv\share\Pasta`: "Pasta"}
	for in, want := range cases {
		if got := baseName(in); got != want {
			t.Errorf("baseName(%q) = %q, quer %q", in, got, want)
		}
	}
}
