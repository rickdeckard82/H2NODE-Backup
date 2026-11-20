package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/runtime"

	"h2node-backup/windows-client/internal/config"
	"h2node-backup/windows-client/internal/engine"
	"h2node-backup/windows-client/internal/ipc"
	"h2node-backup/windows-client/internal/service"
)

// UIState: o estado do serviço + o que só a interface sabe.
type UIState struct {
	service.State
	ServiceOK    bool   `json:"service_ok"`
	ServiceError string `json:"service_error"`
	Admin        bool   `json:"admin"`        // este processo consegue mudar a configuração
	AdminWindow  bool   `json:"admin_window"` // janela aberta "como administrador"
}

// App é a interface: um processo por usuário logado (bandeja) ou a janela elevada
// (--admin). Quem faz backup é o serviço; aqui só se mostra e se pede.
type App struct {
	ctx       context.Context
	adminMode bool
	tray      bool
	user      *ipc.Client
	admin     *ipc.Client
	logger    *log.Logger

	mu       sync.Mutex
	isAdmin  bool
	lastJSON string
	trayIcon *tray
	refresh  chan struct{}
}

func NewApp(trayMode, adminMode bool) *App {
	return &App{
		tray: trayMode, adminMode: adminMode,
		user: ipc.NewClient(ipc.UserPipe), admin: ipc.NewClient(ipc.AdminPipe),
		logger: guiLog(), refresh: make(chan struct{}, 1),
	}
}

func guiLog() *log.Logger {
	dir := filepath.Join(config.LocalDir(), "logs")
	_ = os.MkdirAll(dir, 0o700)
	f, err := os.OpenFile(filepath.Join(dir, "interface.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return log.New(os.Stderr, "", log.LstdFlags)
	}
	return log.New(f, "", log.LstdFlags)
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	if !a.adminMode {
		a.trayIcon = startTray(a)
	}
	go a.poll()
}

func (a *App) shutdown(context.Context) {
	if a.trayIcon != nil {
		stopTray()
	}
	if a.adminMode {
		// fechou a configuração: garante o ícone na bandeja (se já estiver aberto, a
		// segunda instância com --tray não faz nada)
		startTrayAsUser()
	}
}

func (a *App) onSecondInstance(d options.SecondInstanceData) {
	if slices.Contains(d.Args, "--tray") {
		return // pedido para garantir a bandeja: ela já está aberta
	}
	a.ShowWindow()
}

func (a *App) ShowWindow() {
	if a.ctx == nil {
		return
	}
	runtime.WindowShow(a.ctx)
	runtime.WindowUnminimise(a.ctx)
	runtime.WindowSetAlwaysOnTop(a.ctx, true)
	runtime.WindowSetAlwaysOnTop(a.ctx, false)
}

// Quit fecha a interface. O serviço continua fazendo os backups.
func (a *App) Quit() { runtime.Quit(a.ctx) }

// ----------------------------------------------------------------- estado --

func (a *App) fetch() UIState {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var ui UIState
	err := a.user.Call(ctx, "GET", "/state", nil, &ui.State)
	ui.ServiceOK = err == nil
	if err != nil {
		ui.ServiceError = err.Error()
	}
	a.mu.Lock()
	ui.Admin = a.isAdmin
	a.mu.Unlock()
	ui.AdminWindow = a.adminMode
	ui.Items, ui.Excludes, ui.History = nonNil(ui.Items), nonNil(ui.Excludes), nonNil(ui.History)
	return ui
}

func nonNil[T any](s []T) []T {
	if s == nil {
		return []T{}
	}
	return s
}

// checkAdmin: o pipe de administrador só aceita processos elevados.
func (a *App) checkAdmin() {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := a.admin.Call(ctx, "GET", "/state", nil, nil)
	a.mu.Lock()
	a.isAdmin = err == nil
	a.mu.Unlock()
}

// poll consulta o serviço a cada segundo e avisa a interface quando algo muda.
func (a *App) poll() {
	a.checkAdmin()
	lastAdminCheck := time.Now()
	for {
		if time.Since(lastAdminCheck) > 20*time.Second {
			a.checkAdmin()
			lastAdminCheck = time.Now()
		}
		ui := a.fetch()
		b, _ := json.Marshal(ui)
		a.mu.Lock()
		changed := string(b) != a.lastJSON
		a.lastJSON = string(b)
		a.mu.Unlock()
		if changed {
			runtime.EventsEmit(a.ctx, "state", ui)
			a.trayIcon.update(ui)
		}
		select {
		case <-time.After(time.Second):
		case <-a.refresh:
		}
	}
}

func (a *App) kick() {
	select {
	case a.refresh <- struct{}{}:
	default:
	}
}

// GetState: a interface chama ao abrir. Devolve o JSON de UIState como mapa: o gerador
// de tipos do Wails não acompanha o struct embutido de outro pacote (types.ts tem os tipos).
func (a *App) GetState() map[string]any {
	b, _ := json.Marshal(a.fetch())
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	return m
}

// ------------------------------------------------------------- pedidos --

func (a *App) call(adminCall bool, method, path string, in, out any) error {
	cl := a.user
	if adminCall {
		cl = a.admin
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	err := cl.Call(ctx, method, path, in, out)
	if ipc.IsDenied(err) {
		a.mu.Lock()
		a.isAdmin = false
		a.mu.Unlock()
	}
	a.kick()
	return err
}

func (a *App) TestConnection(serverURL, token string) (service.ConnectInfo, error) {
	var info service.ConnectInfo
	err := a.call(true, "POST", "/connect/test", map[string]string{"url": serverURL, "token": token}, &info)
	return info, err
}

func (a *App) ConfirmConnection() error { return a.call(true, "POST", "/connect/confirm", nil, nil) }
func (a *App) Disconnect() error        { return a.call(true, "POST", "/disconnect", nil, nil) }

// ChooseFolder abre o seletor de pasta e pede ao serviço para incluí-la.
func (a *App) ChooseFolder() error {
	dir, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{Title: "Escolha uma pasta para o backup"})
	if err != nil || dir == "" {
		return err
	}
	return a.call(true, "POST", "/items/add", []engine.Item{{Path: dir, IsDir: true}}, nil)
}

func (a *App) ChooseFiles() error {
	files, err := runtime.OpenMultipleFilesDialog(a.ctx, runtime.OpenDialogOptions{Title: "Escolha arquivos para o backup"})
	if err != nil || len(files) == 0 {
		return err
	}
	items := make([]engine.Item, 0, len(files))
	for _, f := range files {
		items = append(items, engine.Item{Path: f})
	}
	return a.call(true, "POST", "/items/add", items, nil)
}

func (a *App) RemoveItem(path string) error {
	return a.call(true, "POST", "/items/remove", map[string]string{"path": path}, nil)
}

func (a *App) SaveExcludes(lines []string) error {
	return a.call(true, "POST", "/excludes", lines, nil)
}

func (a *App) SaveSchedule(s config.Schedule) error { return a.call(true, "POST", "/schedule", s, nil) }

func (a *App) SetVSS(on bool) error {
	return a.call(true, "POST", "/vss", map[string]bool{"enabled": on}, nil)
}

func (a *App) ChooseWorkDir() error {
	dir, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{Title: "Pasta de trabalho (cópias cifradas temporárias)"})
	if err != nil || dir == "" {
		return err
	}
	return a.call(true, "POST", "/workdir", map[string]string{"dir": dir}, nil)
}

func (a *App) RunNow() error { return a.call(false, "POST", "/run", nil, nil) }

func (a *App) Cancel() error { return a.call(false, "POST", "/cancel", nil, nil) }

func (a *App) GetLog() (string, error) {
	var s string
	err := a.call(false, "GET", "/log", nil, &s)
	return s, err
}

// Elevate abre a janela de configuração como administrador (UAC).
func (a *App) Elevate() error {
	err := runElevated("--admin")
	if errors.Is(err, errUACCanceled) {
		return nil
	}
	return err
}

// StartService inicia o serviço (pede UAC).
func (a *App) StartService() error {
	err := runElevated("service", "start")
	if errors.Is(err, errUACCanceled) {
		return nil
	}
	time.AfterFunc(3*time.Second, a.kick)
	return err
}
