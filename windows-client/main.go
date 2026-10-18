// Pulse Backup — cliente Windows.
//
// Um único executável com três papéis:
//
//	PulseBackup.exe service run|install|uninstall|start|stop
//	    o serviço do Windows (LocalSystem) que agenda e faz os backups, com VSS;
//	PulseBackup.exe [--tray]
//	    a interface + ícone na bandeja de cada usuário (mostra, pede "backup agora");
//	PulseBackup.exe --admin
//	    a janela de configuração elevada (UAC): pastas, servidor, agendamento.
package main

import (
	"embed"
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"

	"pulse-backup/windows-client/internal/service"
)

//go:embed all:frontend/dist
var assets embed.FS

// Version vai no manifesto (aparece no painel como versão do agente).
var Version = "0.2.2"

func main() {
	if len(os.Args) > 1 && os.Args[1] == "service" {
		os.Exit(serviceCmd(os.Args[2:]))
	}
	trayMode := flag.Bool("tray", false, "inicia escondido na bandeja (login do Windows)")
	background := flag.Bool("background", false, "o mesmo que --tray (versões anteriores)")
	adminMode := flag.Bool("admin", false, "janela de configuração (elevada)")
	flag.Parse()
	hidden := *trayMode || *background

	app := NewApp(hidden, *adminMode)
	id := "pulse-backup-windows-client-7f3c2a9e"
	if *adminMode {
		id += "-admin" // a janela elevada convive com a da bandeja
	}
	err := wails.Run(&options.App{
		Title:             "Pulse Backup",
		Width:             1000,
		Height:            700,
		MinWidth:          820,
		MinHeight:         560,
		AssetServer:       &assetserver.Options{Assets: assets},
		BackgroundColour:  &options.RGBA{R: 241, G: 245, B: 249, A: 1},
		OnStartup:         app.startup,
		OnShutdown:        app.shutdown,
		HideWindowOnClose: !*adminMode, // bandeja: o X só esconde; janela elevada: fecha
		StartHidden:       hidden && !*adminMode,
		SingleInstanceLock: &options.SingleInstanceLock{
			UniqueId:               id,
			OnSecondInstanceLaunch: app.onSecondInstance,
		},
		Bind:    []interface{}{app},
		Windows: &windows.Options{Theme: windows.SystemDefault},
	})
	if err != nil {
		log.Fatal(err)
	}
}

// serviceCmd: usado pelo instalador (como administrador) e pelo Gerenciador de Serviços.
func serviceCmd(args []string) int {
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "uso: PulseBackup.exe service run|install|uninstall|start|stop")
		return 2
	}
	var err error
	switch args[0] {
	case "run":
		err = service.RunService(Version, osInfo())
	case "install":
		exe, e := os.Executable()
		if e != nil {
			err = e
			break
		}
		err = service.Install(exe)
	case "uninstall":
		err = service.Uninstall()
	case "start":
		err = service.Control(true)
	case "stop":
		err = service.Control(false)
	default:
		err = fmt.Errorf("comando desconhecido: %s", args[0])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "erro:", err)
		return 1
	}
	return 0
}
