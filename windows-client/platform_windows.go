//go:build windows

package main

import (
	"errors"
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

var errUACCanceled = errors.New("elevação cancelada pelo usuário")

// runElevated abre este executável como administrador (janela do UAC).
func runElevated(args ...string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	verb, _ := windows.UTF16PtrFromString("runas")
	file, _ := windows.UTF16PtrFromString(exe)
	params, _ := windows.UTF16PtrFromString(strings.Join(args, " "))
	err = windows.ShellExecute(0, verb, file, params, nil, windows.SW_SHOWNORMAL)
	if errors.Is(err, windows.ERROR_CANCELLED) {
		return errUACCanceled
	}
	return err
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
