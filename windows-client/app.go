package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/runtime"

	"pulse-backup/windows-client/internal/api"
	"pulse-backup/windows-client/internal/config"
	"pulse-backup/windows-client/internal/engine"
)

// UIState é tudo o que a interface mostra (enviado no evento "state").
type UIState struct {
	Version          string           `json:"version"`
	Connected        bool             `json:"connected"`
	ServerURL        string           `json:"server_url"`
	ClientID         string           `json:"client_id"`
	ClientName       string           `json:"client_name"`
	Fingerprint      string           `json:"fingerprint"`
	Items            []engine.Item    `json:"items"`
	Excludes         []string         `json:"excludes"`
	Schedule         config.Schedule  `json:"schedule"`
	WorkDir          string           `json:"work_dir"`
	StartWithWindows bool             `json:"start_with_windows"`
	Running          bool             `json:"running"`
	Progress         *engine.Progress `json:"progress"`
	NextRun          string           `json:"next_run"`     // RFC3339 ou ""
	LastSuccess      string           `json:"last_success"` // RFC3339 ou ""
	History          []engine.Result  `json:"history"`
	LogPath          string           `json:"log_path"`
}

// ConnectInfo: o que o servidor respondeu ao testar a conexão (antes de confirmar).
type ConnectInfo struct {
	ClientID    string `json:"client_id"`
	ClientName  string `json:"client_name"`
	Fingerprint string `json:"fingerprint"`
}

type pendingConn struct {
	url, token string
	hello      *api.Hello
	rcpt       *engine.Recipient
}

type App struct {
	ctx        context.Context
	store      *config.Store
	background bool
	logger     *log.Logger
	logPath    string

	mu        sync.Mutex
	cfg       config.Config
	hist      config.History
	running   bool
	cancel    context.CancelFunc
	progress  *engine.Progress
	nextRun   time.Time
	pending   *pendingConn
	lastEmit  time.Time
	tray      *tray
	wake      chan struct{}
	hostname  string
	osInfo    string
	quitting  bool
}

func NewApp(background bool) (*App, error) {
	store, err := config.NewStore("")
	if err != nil {
		return nil, err
	}
	cfg, err := store.Load()
	if err != nil {
		return nil, fmt.Errorf("configuração corrompida em %s: %w", store.Dir(), err)
	}
	logPath, logger := openLog()
	host, _ := os.Hostname()
	return &App{
		store: store, background: background, cfg: cfg, hist: store.LoadHistory(),
		logger: logger, logPath: logPath, wake: make(chan struct{}, 1),
		hostname: host, osInfo: osInfo(),
	}, nil
}

func (a *App) logf(format string, args ...any) { a.logger.Printf(format, args...) }

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.logf("Pulse Backup %s iniciado (background=%v)", Version, a.background)
	a.tray = startTray(a)
	go a.scheduler()
}

func (a *App) shutdown(context.Context) {
	a.mu.Lock()
	if a.cancel != nil {
		a.cancel()
	}
	a.mu.Unlock()
	stopTray()
}

func (a *App) onSecondInstance(options.SecondInstanceData) { a.ShowWindow() }

// ShowWindow traz a janela (bandeja, segunda instância).
func (a *App) ShowWindow() {
	if a.ctx == nil {
		return
	}
	runtime.WindowShow(a.ctx)
	runtime.WindowUnminimise(a.ctx)
	runtime.WindowSetAlwaysOnTop(a.ctx, true)
	runtime.WindowSetAlwaysOnTop(a.ctx, false)
}

// Quit encerra de verdade (cancela um backup em andamento).
func (a *App) Quit() {
	a.mu.Lock()
	running := a.running
	a.quitting = true
	a.mu.Unlock()
	if running {
		a.logf("saindo durante um backup: cancelado")
	}
	runtime.Quit(a.ctx)
}

// ---------------------------------------------------------------- estado --

func fmtTime(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.Format(time.RFC3339)
}

func (a *App) stateLocked() UIState {
	c := a.cfg
	return UIState{
		Version: Version, Connected: c.Connected(), ServerURL: c.ServerURL, ClientID: c.ClientID,
		ClientName: c.ClientName, Fingerprint: c.Fingerprint, Items: nonNil(c.Items), Excludes: nonNil(c.Excludes),
		Schedule: c.Schedule, WorkDir: c.WorkDir, StartWithWindows: c.StartWithWindows,
		Running: a.running, Progress: a.progress, NextRun: fmtTime(a.nextRun),
		LastSuccess: fmtTime(a.hist.LastSuccess), History: nonNil(a.hist.Runs), LogPath: a.logPath,
	}
}

func nonNil[T any](s []T) []T {
	if s == nil {
		return []T{}
	}
	return s
}

// GetState: a interface chama ao abrir.
func (a *App) GetState() UIState {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.stateLocked()
}

func (a *App) emit() {
	a.mu.Lock()
	st := a.stateLocked()
	a.mu.Unlock()
	if a.ctx != nil {
		runtime.EventsEmit(a.ctx, "state", st)
	}
	a.tray.update(st)
}

func (a *App) saveLocked() error {
	return a.store.Save(a.cfg)
}

// ------------------------------------------------------------- servidor --

// TestConnection confere o endereço e o token e mostra a impressão digital da chave
// GPG do servidor. Nada é salvo até ConfirmConnection.
func (a *App) TestConnection(serverURL, token string) (ConnectInfo, error) {
	token = strings.TrimSpace(token)
	cl, err := api.New(serverURL, token, userAgent())
	if err != nil {
		return ConnectInfo{}, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	h, err := cl.Hello(ctx)
	if err != nil {
		var e *api.Error
		if errors.As(err, &e) && e.Status == 401 {
			return ConnectInfo{}, errors.New("token recusado — gere um novo em Servidores → Windows, no painel")
		}
		return ConnectInfo{}, fmt.Errorf("não foi possível conectar: %w", err)
	}
	rcpt, err := engine.ParsePublicKey(h.PublicKey)
	if err != nil {
		return ConnectInfo{}, err
	}
	if engine.NormalizeFingerprint(h.PublicKeyFingerprint) != rcpt.Fingerprint {
		return ConnectInfo{}, errors.New("a impressão digital informada pelo servidor não confere com a chave recebida")
	}
	a.mu.Lock()
	a.pending = &pendingConn{url: strings.TrimRight(strings.TrimSpace(serverURL), "/"), token: token, hello: h, rcpt: rcpt}
	a.mu.Unlock()
	return ConnectInfo{ClientID: h.ClientID, ClientName: h.ClientName, Fingerprint: rcpt.Fingerprint}, nil
}

// ConfirmConnection salva o servidor, o token (protegido com DPAPI) e fixa a chave pública.
func (a *App) ConfirmConnection() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	p := a.pending
	if p == nil {
		return errors.New("teste a conexão primeiro")
	}
	c := a.cfg
	if err := c.SetToken(p.token); err != nil {
		return err
	}
	c.ServerURL, c.ClientID, c.ClientName = p.url, p.hello.ClientID, p.hello.ClientName
	c.PublicKey, c.Fingerprint = p.hello.PublicKey, p.rcpt.Fingerprint
	a.cfg = c
	a.pending = nil
	if err := a.saveLocked(); err != nil {
		return err
	}
	a.logf("conectado a %s como %s (chave %s)", c.ServerURL, c.ClientID, c.Fingerprint)
	go a.afterChange()
	return nil
}

// Disconnect apaga o token e a chave fixada (os itens e o agendamento ficam).
func (a *App) Disconnect() error {
	a.mu.Lock()
	if a.running {
		a.mu.Unlock()
		return errors.New("aguarde o backup em andamento terminar (ou cancele)")
	}
	a.cfg.ServerURL, a.cfg.TokenProtected, a.cfg.ClientID, a.cfg.ClientName = "", "", "", ""
	a.cfg.PublicKey, a.cfg.Fingerprint = "", ""
	err := a.saveLocked()
	a.mu.Unlock()
	go a.afterChange()
	return err
}

// --------------------------------------------------------------- itens --

func (a *App) addItems(items []engine.Item) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	for _, it := range items {
		it.Path = filepath.Clean(it.Path)
		if slices.ContainsFunc(a.cfg.Items, func(x engine.Item) bool { return strings.EqualFold(x.Path, it.Path) }) {
			continue
		}
		a.cfg.Items = append(a.cfg.Items, it)
	}
	return a.saveLocked()
}

// ChooseFolder abre o seletor de pasta e adiciona a escolhida.
func (a *App) ChooseFolder() error {
	dir, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{Title: "Escolha uma pasta para o backup"})
	if err != nil || dir == "" {
		return err
	}
	if err := a.addItems([]engine.Item{{Path: dir, IsDir: true}}); err != nil {
		return err
	}
	go a.emit()
	return nil
}

// ChooseFiles abre o seletor de arquivos (vários) e adiciona os escolhidos.
func (a *App) ChooseFiles() error {
	files, err := runtime.OpenMultipleFilesDialog(a.ctx, runtime.OpenDialogOptions{Title: "Escolha arquivos para o backup"})
	if err != nil || len(files) == 0 {
		return err
	}
	items := make([]engine.Item, 0, len(files))
	for _, f := range files {
		items = append(items, engine.Item{Path: f})
	}
	if err := a.addItems(items); err != nil {
		return err
	}
	go a.emit()
	return nil
}

// RemoveItem tira um item da lista (o arquivo em si não é tocado).
func (a *App) RemoveItem(path string) error {
	a.mu.Lock()
	a.cfg.Items = slices.DeleteFunc(a.cfg.Items, func(x engine.Item) bool { return x.Path == path })
	err := a.saveLocked()
	a.mu.Unlock()
	go a.emit()
	return err
}

// SaveExcludes grava os padrões de exclusão (um por linha).
func (a *App) SaveExcludes(lines []string) error {
	var out []string
	for _, l := range lines {
		if l = strings.TrimSpace(l); l != "" {
			if _, err := filepath.Match(strings.ToLower(l), "x"); err != nil {
				return fmt.Errorf("padrão inválido: %q", l)
			}
			out = append(out, l)
		}
	}
	a.mu.Lock()
	a.cfg.Excludes = out
	err := a.saveLocked()
	a.mu.Unlock()
	go a.emit()
	return err
}

// ChooseWorkDir troca a pasta de trabalho (precisa caber o maior item cifrado).
func (a *App) ChooseWorkDir() error {
	dir, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{Title: "Pasta de trabalho (cópias cifradas temporárias)"})
	if err != nil || dir == "" {
		return err
	}
	a.mu.Lock()
	a.cfg.WorkDir = filepath.Join(dir, "PulseBackup-work")
	err = a.saveLocked()
	a.mu.Unlock()
	go a.emit()
	return err
}

// --------------------------------------------------------- agendamento --

func (a *App) SaveSchedule(s config.Schedule) error {
	if err := s.Validate(); err != nil {
		return err
	}
	a.mu.Lock()
	a.cfg.Schedule = s
	err := a.saveLocked()
	a.mu.Unlock()
	if err == nil {
		go a.afterChange()
	}
	return err
}

func (a *App) SetStartWithWindows(on bool) error {
	if err := setAutostart(on); err != nil {
		return fmt.Errorf("não foi possível alterar a inicialização com o Windows: %w", err)
	}
	a.mu.Lock()
	a.cfg.StartWithWindows = on
	err := a.saveLocked()
	a.mu.Unlock()
	go a.emit()
	return err
}

// OpenLog e OpenWorkDir abrem no Explorer.
func (a *App) OpenLog() error { return openPath(a.logPath) }

func (a *App) OpenConfigDir() error { return openPath(a.store.Dir()) }

// ------------------------------------------------------------- backup --

// RunNow inicia um backup agora (botão ou bandeja).
func (a *App) RunNow() error { return a.startBackup("manual") }

// Cancel interrompe o backup em andamento.
func (a *App) Cancel() {
	a.mu.Lock()
	if a.cancel != nil {
		a.cancel()
	}
	a.mu.Unlock()
}

func userAgent() string { return "PulseBackupWindows/" + Version }

func (a *App) startBackup(reason string) error {
	a.mu.Lock()
	if a.running {
		a.mu.Unlock()
		return errors.New("já existe um backup em andamento")
	}
	c := a.cfg
	if !c.Connected() {
		a.mu.Unlock()
		return errors.New("conecte ao servidor primeiro (aba Servidor)")
	}
	if len(c.Items) == 0 {
		a.mu.Unlock()
		return engine.ErrNoItems
	}
	token, err := c.Token()
	if err != nil {
		a.mu.Unlock()
		return err
	}
	rcpt, err := engine.ParsePublicKey(c.PublicKey)
	if err != nil {
		a.mu.Unlock()
		return err
	}
	cl, err := api.New(c.ServerURL, token, userAgent())
	if err != nil {
		a.mu.Unlock()
		return err
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.running, a.cancel = true, cancel
	a.progress = &engine.Progress{Phase: "preparing", Count: len(c.Items)}
	a.mu.Unlock()
	a.emit()
	a.logf("backup iniciado (%s)", reason)

	go func() {
		defer cancel()
		res := a.runBackup(ctx, cl, c, rcpt)
		h, err := a.store.AddRun(res)
		if err != nil {
			a.logf("não foi possível gravar o histórico: %v", err)
		}
		a.mu.Lock()
		a.hist = h
		a.running, a.cancel, a.progress = false, nil, nil
		a.mu.Unlock()
		a.scheduleNext(res)
		a.emit()
		a.notify(res)
	}()
	return nil
}

func (a *App) runBackup(ctx context.Context, cl *api.Client, c config.Config, rcpt *engine.Recipient) engine.Result {
	// confere o servidor antes de começar: token válido e a MESMA chave fixada ao conectar
	h, err := cl.Hello(ctx)
	if err != nil {
		return engine.Result{StartedAt: time.Now().UTC(), FinishedAt: time.Now().UTC(), Status: "failed",
			Errors: []string{"servidor indisponível ou token recusado: " + err.Error()}}
	}
	if engine.NormalizeFingerprint(h.PublicKeyFingerprint) != rcpt.Fingerprint {
		msg := fmt.Sprintf("a chave GPG do servidor mudou (%s → %s): reconecte na aba Servidor depois de conferir com o administrador",
			rcpt.Fingerprint, h.PublicKeyFingerprint)
		a.logf("%s", msg)
		return engine.Result{StartedAt: time.Now().UTC(), FinishedAt: time.Now().UTC(), Status: "failed", Errors: []string{msg}}
	}
	engine.SetChunkSize(h.ChunkMax)
	return engine.Run(ctx, cl, engine.Options{
		ClientID: c.ClientID, Recipient: rcpt, Items: c.Items, Excludes: c.Excludes, WorkDir: c.WorkDir,
		Version: "win-" + Version, Hostname: a.hostname, OSInfo: a.osInfo,
	}, a.onProgress, a.logf)
}

// onProgress repassa à interface no máximo 4x por segundo (e sempre na troca de fase).
func (a *App) onProgress(p engine.Progress) {
	a.mu.Lock()
	phaseChanged := a.progress == nil || a.progress.Phase != p.Phase || a.progress.Index != p.Index
	a.progress = &p
	if !phaseChanged && time.Since(a.lastEmit) < 250*time.Millisecond {
		a.mu.Unlock()
		return
	}
	a.lastEmit = time.Now()
	a.mu.Unlock()
	if a.ctx != nil {
		runtime.EventsEmit(a.ctx, "progress", p)
	}
	if phaseChanged {
		a.tray.update(a.GetState())
	}
}

func (a *App) notify(r engine.Result) {
	msg := map[string]string{
		"success": "Backup concluído", "partial": "Backup concluído com falhas",
		"failed": "Backup falhou", "canceled": "Backup cancelado",
	}[r.Status]
	a.logf("%s (%s): %d bytes, erros: %s", msg, r.RunName, r.Bytes, strings.Join(r.Errors, " | "))
}

// ---------------------------------------------------------- agendador --

func (a *App) afterChange() {
	a.mu.Lock()
	a.nextRun = a.cfg.Schedule.Next(time.Now(), a.hist.LastAttempt)
	a.mu.Unlock()
	a.emit()
	select {
	case a.wake <- struct{}{}:
	default:
	}
}

// scheduleNext: depois de uma falha, tenta de novo em 1 h (se o próximo horário estiver longe).
func (a *App) scheduleNext(r engine.Result) {
	a.mu.Lock()
	defer a.mu.Unlock()
	now := time.Now()
	next := a.cfg.Schedule.Next(now, a.hist.LastAttempt)
	if (r.Status == "failed") && a.cfg.Schedule.Mode != "manual" {
		retry := now.Add(time.Hour)
		if next.IsZero() || retry.Before(next) {
			next = retry
		}
	}
	a.nextRun = next
}

func (a *App) scheduler() {
	a.mu.Lock()
	s, last := a.cfg.Schedule, a.hist.LastAttempt
	if s.Missed(time.Now(), last) {
		a.nextRun = time.Now().Add(2 * time.Minute) // perdeu o horário: roda logo depois de abrir
		a.logf("backup agendado perdido (último: %s): roda em 2 minutos", last.Local().Format("02/01 15:04"))
	} else {
		a.nextRun = s.Next(time.Now(), last)
	}
	a.mu.Unlock()
	a.emit()

	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-t.C:
		case <-a.wake:
		}
		a.mu.Lock()
		due := !a.nextRun.IsZero() && !time.Now().Before(a.nextRun) && !a.running && !a.quitting
		ready := a.cfg.Connected() && len(a.cfg.Items) > 0
		a.mu.Unlock()
		if !due {
			continue
		}
		if !ready {
			a.mu.Lock()
			a.nextRun = a.cfg.Schedule.Next(time.Now(), time.Now())
			a.mu.Unlock()
			a.emit()
			continue
		}
		if err := a.startBackup("agendado"); err != nil {
			a.logf("backup agendado não iniciou: %v", err)
		}
	}
}

// ---------------------------------------------------------------- log --

func openLog() (string, *log.Logger) {
	dir := filepath.Join(config.LocalDir(), "logs")
	_ = os.MkdirAll(dir, 0o700)
	path := filepath.Join(dir, "pulse-backup.log")
	if st, err := os.Stat(path); err == nil && st.Size() > 5<<20 {
		_ = os.Rename(path, path+".1") // um arquivo anterior basta
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return path, log.New(os.Stderr, "", log.LstdFlags)
	}
	return path, log.New(f, "", log.LstdFlags)
}
