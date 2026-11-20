// genicon grava build/appicon.png (o Wails gera o icon.ico do executável a partir dele).
//
//	go run ./tools/genicon
package main

import (
	"os"
	"path/filepath"

	"h2node-backup/windows-client/internal/icon"
)

func main() {
	out := filepath.Join("build", "appicon.png")
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		panic(err)
	}
	if err := os.WriteFile(out, icon.PNG(1024, ""), 0o644); err != nil {
		panic(err)
	}
}
