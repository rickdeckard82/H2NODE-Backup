// Pulse Backup — cliente Windows.
//
// Um único executável: interface gráfica (Wails) + ícone na bandeja + agendador.
// Fechar a janela só a esconde; o backup continua rodando em segundo plano até
// "Sair" no ícone da bandeja. Com "Iniciar com o Windows", abre escondido
// (--background) no login do usuário.
package main

import (
	"embed"
	"flag"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

// Version vai no manifesto (aparece no painel como versão do agente).
var Version = "0.1.0"

func main() {
	background := flag.Bool("background", false, "inicia escondido na bandeja (usado no login do Windows)")
	flag.Parse()

	app, err := NewApp(*background)
	if err != nil {
		log.Fatal(err)
	}
	err = wails.Run(&options.App{
		Title:             "Pulse Backup",
		Width:             1000,
		Height:            700,
		MinWidth:          820,
		MinHeight:         560,
		AssetServer:       &assetserver.Options{Assets: assets},
		BackgroundColour:  &options.RGBA{R: 241, G: 245, B: 249, A: 1},
		OnStartup:         app.startup,
		OnShutdown:        app.shutdown,
		HideWindowOnClose: true, // o X só esconde; sair é pela bandeja
		StartHidden:       *background,
		SingleInstanceLock: &options.SingleInstanceLock{
			UniqueId:               "pulse-backup-windows-client-7f3c2a9e",
			OnSecondInstanceLaunch: app.onSecondInstance,
		},
		Bind: []interface{}{app},
		Windows: &windows.Options{
			Theme: windows.SystemDefault,
		},
	})
	if err != nil {
		log.Fatal(err)
	}
}
