//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"

	"golang.org/x/sys/windows/registry"
)

const runKey = `Software\Microsoft\Windows\CurrentVersion\Run`

// setAutostart liga/desliga a abertura no login (HKCU\...\Run, só deste usuário).
func setAutostart(on bool) error {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, runKey, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()
	if !on {
		if err := k.DeleteValue("PulseBackup"); err != nil && err != registry.ErrNotExist {
			return err
		}
		return nil
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	return k.SetStringValue("PulseBackup", fmt.Sprintf(`"%s" --background`, exe))
}

// osInfo: "Windows 11 Pro 24H2 (build 26100)". O registro diz "Windows 10" também no
// 11, então o número do build decide.
func osInfo() string {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\Windows NT\CurrentVersion`, registry.QUERY_VALUE)
	if err != nil {
		return "Windows"
	}
	defer k.Close()
	name, _, _ := k.GetStringValue("ProductName")
	disp, _, _ := k.GetStringValue("DisplayVersion")
	build, _, _ := k.GetStringValue("CurrentBuildNumber")
	if n, err := strconv.Atoi(build); err == nil && n >= 22000 {
		name = strings.Replace(name, "Windows 10", "Windows 11", 1)
	}
	s := strings.TrimSpace(name + " " + disp)
	if build != "" {
		s += " (build " + build + ")"
	}
	return s
}

// openPath abre um arquivo ou pasta no Explorer.
func openPath(p string) error {
	cmd := exec.Command("explorer.exe", p)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Start() // explorer.exe devolve código 1 mesmo quando abre
	return nil
}
