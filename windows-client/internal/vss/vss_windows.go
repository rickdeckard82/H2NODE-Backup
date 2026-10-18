//go:build windows

package vss

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// As cópias são criadas pelo WMI (Win32_ShadowCopy.Create, contexto
// "ClientAccessible" — o único aceito no Windows 10/11; o vssadmin só cria no
// Server). Pelo PowerShell que vem no Windows: sem CGO nem COM no processo.
var guidRe = regexp.MustCompile(`^\{[0-9A-Fa-f-]{36}\}$`)

func powershell(ctx context.Context, script string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Minute)
	defer cancel()
	exe := filepath.Join(os.Getenv("SystemRoot"), `System32\WindowsPowerShell\v1.0\powershell.exe`)
	cmd := exec.CommandContext(ctx, exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
	out, err := cmd.CombinedOutput()
	s := strings.TrimSpace(string(out))
	if err != nil {
		if s == "" {
			s = err.Error()
		}
		return "", errors.New(lastLines(s, 3))
	}
	return s, nil
}

func lastLines(s string, n int) string {
	ls := strings.Split(strings.ReplaceAll(s, "\r", ""), "\n")
	if len(ls) > n {
		ls = ls[len(ls)-n:]
	}
	return strings.Join(ls, " ")
}

// supported: só volumes locais fixos (NTFS/ReFS). Pendrive, rede e CD ficam de fora.
func supported(vol string) error {
	root, _ := windows.UTF16PtrFromString(vol + `\`)
	if t := windows.GetDriveType(root); t != windows.DRIVE_FIXED {
		return fmt.Errorf("unidade %s não é um disco local fixo", vol)
	}
	var fs [64]uint16
	if err := windows.GetVolumeInformation(root, nil, 0, nil, nil, nil, &fs[0], uint32(len(fs))); err != nil {
		return err
	}
	if name := windows.UTF16ToString(fs[:]); name != "NTFS" && name != "ReFS" {
		return fmt.Errorf("sistema de arquivos %s não tem VSS", name)
	}
	return nil
}

// Create cria uma cópia de sombra para cada volume. Volumes que falham ficam em
// Failed (o backup lê esses arquivos ao vivo). record é chamado com cada cópia criada
// ANTES de usá-la, para a limpeza de órfãs se o serviço cair no meio.
func Create(ctx context.Context, volumes []string, record func(Snapshot)) *Set {
	set := &Set{Snaps: map[string]Snapshot{}, Failed: map[string]string{}}
	sort.Strings(volumes)
	for _, vol := range volumes {
		if err := supported(vol); err != nil {
			set.Failed[vol] = err.Error()
			continue
		}
		script := fmt.Sprintf(`$ErrorActionPreference='Stop'
$r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create -Arguments @{Volume='%s\'; Context='ClientAccessible'}
if ($r.ReturnValue -ne 0) { throw "Win32_ShadowCopy.Create retornou $($r.ReturnValue)" }
$s = Get-CimInstance Win32_ShadowCopy -Filter "ID='$($r.ShadowID)'"
@{id=$s.ID; device=$s.DeviceObject} | ConvertTo-Json -Compress`, vol)
		out, err := powershell(ctx, script)
		if err != nil {
			set.Failed[vol] = "VSS: " + explain(err.Error())
			continue
		}
		var r struct{ ID, Device string }
		if err := json.Unmarshal([]byte(lastLines(out, 1)), &r); err != nil || !guidRe.MatchString(r.ID) ||
			!strings.HasPrefix(r.Device, `\\?\GLOBALROOT\Device\`) {
			set.Failed[vol] = "VSS: resposta inesperada do WMI: " + lastLines(out, 1)
			continue
		}
		snap := Snapshot{Volume: vol, ID: r.ID, Device: r.Device}
		if record != nil {
			record(snap)
		}
		set.Snaps[vol] = snap
	}
	return set
}

// códigos de Win32_ShadowCopy.Create mais comuns, em português
func explain(msg string) string {
	codes := map[string]string{
		"retornou 1":  "acesso negado (o serviço precisa rodar como administrador/SYSTEM)",
		"retornou 5":  "volume não suportado",
		"retornou 10": "o serviço de cópias de sombra está ocupado; tente de novo",
		"retornou 11": "muitas cópias de sombra no volume",
		"retornou 12": "sem espaço para a cópia de sombra (aumente o armazenamento em vssadmin/Proteção do sistema)",
	}
	for k, v := range codes {
		if strings.Contains(msg, k+" ") || strings.HasSuffix(msg, k) {
			return v
		}
	}
	return msg
}

// Delete apaga as cópias (no fim do backup e na limpeza de órfãs).
func Delete(ctx context.Context, ids []string) error {
	var valid []string
	for _, id := range ids {
		if guidRe.MatchString(id) {
			valid = append(valid, "'"+id+"'")
		}
	}
	if len(valid) == 0 {
		return nil
	}
	script := fmt.Sprintf(`$ErrorActionPreference='Stop'
foreach ($id in @(%s)) { Get-CimInstance Win32_ShadowCopy -Filter "ID='$id'" | Remove-CimInstance }`, strings.Join(valid, ","))
	_, err := powershell(ctx, script)
	return err
}

// Release apaga todas as cópias do conjunto.
func (s *Set) Release(ctx context.Context) error {
	if s == nil || len(s.Snaps) == 0 {
		return nil
	}
	ids := make([]string, 0, len(s.Snaps))
	for _, sn := range s.Snaps {
		ids = append(ids, sn.ID)
	}
	return Delete(ctx, ids)
}

// VolumeDevice: \\?\GLOBALROOT\Device\HarddiskVolumeN do volume vivo (para testes).
func VolumeDevice(vol string) (string, error) {
	name, _ := windows.UTF16PtrFromString(vol)
	buf := make([]uint16, 512)
	if _, err := windows.QueryDosDevice(name, &buf[0], uint32(len(buf))); err != nil {
		return "", err
	}
	return `\\?\GLOBALROOT` + windows.UTF16ToString(buf), nil
}
