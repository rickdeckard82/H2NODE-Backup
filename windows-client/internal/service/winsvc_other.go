//go:build !windows

package service

import "errors"

var errOnlyWindows = errors.New("o serviço só existe no Windows")

func RunService(string, string) error { return errOnlyWindows }
func Install(string) error            { return errOnlyWindows }
func Uninstall() error                { return errOnlyWindows }
func Control(bool) error              { return errOnlyWindows }
func DataDir() string                 { return "" }
