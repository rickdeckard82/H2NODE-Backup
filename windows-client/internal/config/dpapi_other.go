//go:build !windows

package config

// Fora do Windows (só para compilar os testes): sem proteção.
func protect(b []byte) ([]byte, error)   { return append([]byte(nil), b...), nil }
func unprotect(b []byte) ([]byte, error) { return append([]byte(nil), b...), nil }
