// Package vss cria cópias de sombra (Volume Shadow Copy) dos volumes que entram no
// backup, para ler arquivos abertos e travados (Outlook .pst, bancos, planilhas
// abertas) num estado consistente. Exige administrador — roda no serviço (SYSTEM).
//
// Os arquivos são lidos direto pelo dispositivo da cópia
// (\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\...), sem montar letra de unidade
// (uma letra apareceria para todos os usuários no Explorer).
package vss

import (
	"path/filepath"
	"strings"
)

// Snapshot é uma cópia de sombra de um volume.
type Snapshot struct {
	Volume string `json:"volume"` // "C:"
	ID     string `json:"id"`     // {GUID} do Win32_ShadowCopy
	Device string `json:"device"` // \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN
}

// Set mapeia volumes para cópias de sombra.
type Set struct {
	Snaps  map[string]Snapshot // por volume em maiúsculas ("C:")
	Failed map[string]string   // volume -> motivo (lido ao vivo)
}

// VolumeOf devolve "C:" para C:\…; vazio para caminhos de rede (\\servidor\…).
func VolumeOf(path string) string {
	v := filepath.VolumeName(path)
	if len(v) == 2 && v[1] == ':' {
		return strings.ToUpper(v)
	}
	return ""
}

// Translate troca o volume do caminho pelo dispositivo da cópia de sombra.
// ok=false: o volume não tem cópia (ler o caminho original).
func (s *Set) Translate(path string) (string, bool) {
	if s == nil {
		return path, false
	}
	vol := VolumeOf(path)
	snap, ok := s.Snaps[vol]
	if !ok {
		return path, false
	}
	rest := strings.TrimLeft(path[len(vol):], `\/`)
	return TranslateTo(snap.Device, rest), true
}

// TranslateTo junta o dispositivo e o resto do caminho (sem Clean: ele mexeria no
// prefixo \\?\).
func TranslateTo(device, rest string) string {
	device = strings.TrimRight(device, `\`)
	if rest == "" {
		return device + `\`
	}
	return device + `\` + strings.ReplaceAll(rest, "/", `\`)
}
