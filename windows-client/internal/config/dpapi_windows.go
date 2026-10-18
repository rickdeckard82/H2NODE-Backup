//go:build windows

package config

import (
	"unsafe"

	"golang.org/x/sys/windows"
)

func blob(b []byte) *windows.DataBlob {
	if len(b) == 0 {
		return &windows.DataBlob{}
	}
	return &windows.DataBlob{Size: uint32(len(b)), Data: &b[0]}
}

func dpapi(in []byte, encrypt bool) ([]byte, error) {
	var out windows.DataBlob
	var err error
	if encrypt {
		err = windows.CryptProtectData(blob(in), nil, nil, 0, nil, windows.CRYPTPROTECT_UI_FORBIDDEN, &out)
	} else {
		err = windows.CryptUnprotectData(blob(in), nil, nil, 0, nil, windows.CRYPTPROTECT_UI_FORBIDDEN, &out)
	}
	if err != nil {
		return nil, err
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data)))
	return append([]byte(nil), unsafe.Slice(out.Data, out.Size)...), nil
}

func protect(b []byte) ([]byte, error)   { return dpapi(b, true) }
func unprotect(b []byte) ([]byte, error) { return dpapi(b, false) }
