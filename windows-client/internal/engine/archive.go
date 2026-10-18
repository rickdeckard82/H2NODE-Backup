package engine

import (
	"archive/tar"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// ArchiveStats resume o que entrou (ou não) no tar de uma pasta.
type ArchiveStats struct {
	Files   int
	Dirs    int
	Bytes   int64
	Skipped []string // arquivos que não puderam ser lidos (em uso, sem permissão…)
	Partial []string // arquivos lidos pela metade (mudaram de tamanho durante a leitura)
}

// excluded: padrões no nome do arquivo/pasta, sem diferenciar maiúsculas (ex.: *.tmp, ~$*, Thumbs.db).
func excluded(name string, patterns []string) bool {
	low := strings.ToLower(name)
	for _, p := range patterns {
		p = strings.ToLower(strings.TrimSpace(p))
		if p == "" {
			continue
		}
		if ok, _ := filepath.Match(p, low); ok {
			return true
		}
	}
	return false
}

// writeTar grava a pasta `root` em `tw`, com caminhos relativos começando por `base`
// (o nome da pasta original: Documentos/…, mesmo lendo da cópia de sombra) e "/". Não segue links simbólicos nem
// junções (evita laços, como "Dados de Aplicativos" no perfil do Windows). Só LÊ os
// arquivos de origem.
func writeTar(ctx context.Context, root, base string, excludes []string, tw *tar.Writer, onBytes func(int64)) (*ArchiveStats, error) {
	st := &ArchiveStats{}
	if !strings.HasPrefix(root, `\\?\`) {
		root = filepath.Clean(root) // Clean mexeria no prefixo \\?\ da cópia de sombra
	}
	buf := make([]byte, 1<<20)
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, walkErr error) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if walkErr != nil {
			if p == root {
				return walkErr
			}
			st.Skipped = append(st.Skipped, p+": "+walkErr.Error())
			if d != nil && d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if p != root && excluded(d.Name(), excludes) {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		// links simbólicos, junções e pontos de montagem: não entram nem são seguidos
		if d.Type()&(fs.ModeSymlink|fs.ModeIrregular) != 0 {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		name := base
		if rel != "." {
			name = base + "/" + filepath.ToSlash(rel)
		}
		info, err := d.Info()
		if err != nil {
			st.Skipped = append(st.Skipped, p+": "+err.Error())
			return nil
		}
		if d.IsDir() {
			st.Dirs++
			return tw.WriteHeader(&tar.Header{
				Typeflag: tar.TypeDir, Name: name + "/", Mode: 0o755, ModTime: info.ModTime(), Format: tar.FormatPAX,
			})
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		f, err := os.Open(p)
		if err != nil {
			// em uso por outro programa (ex.: .pst do Outlook aberto) ou sem permissão
			st.Skipped = append(st.Skipped, p+": "+err.Error())
			return nil
		}
		defer f.Close()
		size := info.Size()
		if err := tw.WriteHeader(&tar.Header{
			Typeflag: tar.TypeReg, Name: name, Size: size, Mode: 0o644, ModTime: info.ModTime(), Format: tar.FormatPAX,
		}); err != nil {
			return err
		}
		n, cerr := io.CopyBuffer(tw, io.LimitReader(&ctxReader{ctx, f, onBytes}, size), buf)
		if cerr != nil && errors.Is(cerr, ctx.Err()) {
			return cerr
		}
		if n < size {
			// leitura falhou ou o arquivo encolheu: completa com zeros para o tar continuar válido
			if _, err := io.CopyN(tw, zeroReader{}, size-n); err != nil {
				return err
			}
			msg := fmt.Sprintf("%s: lido %d de %d bytes", p, n, size)
			if cerr != nil {
				msg += " (" + cerr.Error() + ")"
			}
			st.Partial = append(st.Partial, msg)
		}
		st.Files++
		st.Bytes += size
		return nil
	})
	return st, err
}

type zeroReader struct{}

func (zeroReader) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}

// ctxReader interrompe a leitura quando o backup é cancelado e conta o progresso.
type ctxReader struct {
	ctx     context.Context
	r       io.Reader
	onBytes func(int64)
}

func (c *ctxReader) Read(p []byte) (int, error) {
	if err := c.ctx.Err(); err != nil {
		return 0, err
	}
	n, err := c.r.Read(p)
	if n > 0 && c.onBytes != nil {
		c.onBytes(int64(n))
	}
	return n, err
}
