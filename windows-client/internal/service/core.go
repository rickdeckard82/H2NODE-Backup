// Package service é o que roda dentro do serviço do Windows (LocalSystem): agenda e
// faz os backups (com VSS), guarda a configuração em %ProgramData%\PulseBackup e
// atende a interface pelos named pipes (http.go).
package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"pulse-backup/windows-client/internal/api"
	"pulse-backup/windows-client/internal/config"
	"pulse-backup/windows-client/internal/engine"
	"pulse-backup/windows-client/internal/vss"
)

// State é o que a interface mostra.
type State struct {
	Version     string           `json:"version"`
	Connected   bool             `json:"connected"`
	ServerURL   string           `json:"server_url"`
	ClientID    string           `json:"client_id"`
	ClientName  string           `json:"client_name"`
	Fingerprint string           `json:"fingerprint"`
	Items       []engine.Item    `json:"items"`
	Excludes    []string         `json:"excludes"`
	Schedule    config.Schedule  `json:"schedule"`
	WorkDir     string           `json:"work_dir"`
	UseVSS      bool             `json:"use_vss"`
	Running     bool             `json:"running"`
	Progress    *engine.Progress `json:"progress"`
	NextRun     string           `json:"next_run"`
	LastSuccess string           `json:"last_success"`
	History     []engine.Result  `json:"history"`
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
	at         time.Time
}

type Core struct {
	version  string
	store    *config.Store
	logger   *log.Logger
	logFile  io.Closer
	logPath  string
	hostname string
	osInfo   string
	vssState string // cópias de sombra em uso (limpeza de órfãs)

	mu       sync.Mutex
	cfg      config.Config
	hist     config.History
	running  bool
	cancel   context.CancelFunc
	done     chan struct{}
	progress *engine.Progress
	nextRun  time.Time
	pending  *pendingConn
	wake     chan struct{}
	stopping bool
}

// New abre (ou cria) a configuração em dataDir.
func New(dataDir, version, osInfo string) (*Core, error) {
	store, err := config.NewStore(dataDir)
	if err != nil {
		return nil, err
	}
	cfg, err := store.Load()
	if err != nil {
		return nil, fmt.Errorf("configuração corrompida em %s: %w", store.Dir(), err)
	}
	if cfg.WorkDir == "" {
		cfg.WorkDir = filepath.Join(dataDir, "work")
	}
	logPath, logger, logFile := openLog(filepath.Join(dataDir, "logs"))
	host, _ := os.Hostname()
	return &Core{
		version: version, store: store, logger: logger, logFile: logFile, logPath: logPath, hostname: host, osInfo: osInfo,
		vssState: filepath.Join(dataDir, "vss.json"),
		cfg:      cfg, hist: store.LoadHistory(), wake: make(chan struct{}, 1),
	}, nil
}

func (c *Core) logf(format string, args ...any) { c.logger.Printf(format, args...) }

// ------------------------------------------------------------------ estado --

func fmtTime(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.Format(time.RFC3339)
}

func nonNil[T any](s []T) []T {
	if s == nil {
		return []T{}
	}
	return s
}

func (c *Core) State() State {
	c.mu.Lock()
	defer c.mu.Unlock()
	k := c.cfg
	return State{
		Version: c.version, Connected: k.Connected(), ServerURL: k.ServerURL, ClientID: k.ClientID,
		ClientName: k.ClientName, Fingerprint: k.Fingerprint, Items: nonNil(k.Items), Excludes: nonNil(k.Excludes),
		Schedule: k.Schedule, WorkDir: k.WorkDir, UseVSS: k.UseVSS, Running: c.running, Progress: c.progress,
		NextRun: fmtTime(c.nextRun), LastSuccess: fmtTime(c.hist.LastSuccess), History: nonNil(c.hist.Runs),
	}
}

// mutate aplica uma mudança na configuração e salva (recusa durante um backup quando pedido).
func (c *Core) mutate(blockWhileRunning bool, fn func(*config.Config) error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if blockWhileRunning && c.running {
		return errors.New("aguarde o backup em andamento terminar (ou cancele)")
	}
	next := c.cfg
	next.Items = slices.Clone(c.cfg.Items)
	if err := fn(&next); err != nil {
		return err
	}
	if err := c.store.Save(next); err != nil {
		return err
	}
	c.cfg = next
	return nil
}

func (c *Core) poke() {
	c.mu.Lock()
	c.nextRun = c.cfg.Schedule.Next(time.Now(), c.hist.LastAttempt)
	c.mu.Unlock()
	select {
	case c.wake <- struct{}{}:
	default:
	}
}

// ---------------------------------------------------------------- servidor --

func userAgent(v string) string { return "PulseBackupWindows/" + v }

// TestConnection confere endereço e token e devolve a impressão digital da chave GPG.
// Nada é salvo até ConfirmConnection.
func (c *Core) TestConnection(ctx context.Context, serverURL, token string) (ConnectInfo, error) {
	token = strings.TrimSpace(token)
	cl, err := api.New(serverURL, token, userAgent(c.version))
	if err != nil {
		return ConnectInfo{}, err
	}
	cl.SetRetries(1) // teste manual: responde logo, sem novas tentativas
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
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
	c.mu.Lock()
	c.pending = &pendingConn{url: strings.TrimRight(strings.TrimSpace(serverURL), "/"), token: token, hello: h, rcpt: rcpt, at: time.Now()}
	c.mu.Unlock()
	return ConnectInfo{ClientID: h.ClientID, ClientName: h.ClientName, Fingerprint: rcpt.Fingerprint}, nil
}

// ConfirmConnection salva o servidor e o token (DPAPI da conta SYSTEM) e fixa a chave.
func (c *Core) ConfirmConnection() error {
	c.mu.Lock()
	p := c.pending
	c.pending = nil
	c.mu.Unlock()
	if p == nil || time.Since(p.at) > 15*time.Minute {
		return errors.New("teste a conexão primeiro")
	}
	err := c.mutate(true, func(k *config.Config) error {
		if err := k.SetToken(p.token); err != nil {
			return err
		}
		k.ServerURL, k.ClientID, k.ClientName = p.url, p.hello.ClientID, p.hello.ClientName
		k.PublicKey, k.Fingerprint = p.hello.PublicKey, p.rcpt.Fingerprint
		return nil
	})
	if err == nil {
		c.logf("conectado a %s como %s (chave %s)", p.url, p.hello.ClientID, p.rcpt.Fingerprint)
		c.poke()
	}
	return err
}

func (c *Core) Disconnect() error {
	err := c.mutate(true, func(k *config.Config) error {
		k.ServerURL, k.TokenProtected, k.ClientID, k.ClientName, k.PublicKey, k.Fingerprint = "", "", "", "", "", ""
		return nil
	})
	if err == nil {
		c.logf("desconectado do servidor")
	}
	return err
}

// ------------------------------------------------------------------- itens --

func (c *Core) AddItems(items []engine.Item) error {
	for _, it := range items {
		if !filepath.IsAbs(it.Path) {
			return fmt.Errorf("caminho inválido: %q", it.Path)
		}
		info, err := os.Stat(it.Path)
		if err != nil {
			return fmt.Errorf("o serviço não consegue acessar %s: %v (unidades de rede mapeadas não existem para o serviço: use \\\\servidor\\pasta)", it.Path, err)
		}
		if info.IsDir() != it.IsDir {
			return fmt.Errorf("%s mudou de tipo", it.Path)
		}
	}
	return c.mutate(true, func(k *config.Config) error {
		for _, it := range items {
			it.Path = filepath.Clean(it.Path)
			if !slices.ContainsFunc(k.Items, func(x engine.Item) bool { return strings.EqualFold(x.Path, it.Path) }) {
				k.Items = append(k.Items, engine.Item{Path: it.Path, IsDir: it.IsDir})
			}
		}
		return nil
	})
}

func (c *Core) RemoveItem(path string) error {
	return c.mutate(true, func(k *config.Config) error {
		k.Items = slices.DeleteFunc(k.Items, func(x engine.Item) bool { return x.Path == path })
		return nil
	})
}

func (c *Core) SetExcludes(lines []string) error {
	var out []string
	for _, l := range lines {
		if l = strings.TrimSpace(l); l != "" {
			if _, err := filepath.Match(strings.ToLower(l), "x"); err != nil {
				return fmt.Errorf("padrão inválido: %q", l)
			}
			out = append(out, l)
		}
	}
	return c.mutate(false, func(k *config.Config) error { k.Excludes = out; return nil })
}

func (c *Core) SetSchedule(s config.Schedule) error {
	if err := s.Validate(); err != nil {
		return err
	}
	err := c.mutate(false, func(k *config.Config) error { k.Schedule = s; return nil })
	if err == nil {
		c.poke()
	}
	return err
}

func (c *Core) SetWorkDir(dir string) error {
	if !filepath.IsAbs(dir) {
		return fmt.Errorf("pasta inválida: %q", dir)
	}
	dir = filepath.Join(dir, "PulseBackup-work")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("o serviço não consegue criar %s: %w", dir, err)
	}
	return c.mutate(true, func(k *config.Config) error { k.WorkDir = dir; return nil })
}

func (c *Core) SetVSS(on bool) error {
	return c.mutate(false, func(k *config.Config) error { k.UseVSS = on; return nil })
}

// LogTail: o fim do log (para a interface mostrar sem dar acesso à pasta).
func (c *Core) LogTail(max int64) string {
	f, err := os.Open(c.logPath)
	if err != nil {
		return ""
	}
	defer f.Close()
	if st, err := f.Stat(); err == nil && st.Size() > max {
		f.Seek(st.Size()-max, io.SeekStart)
	}
	b, _ := io.ReadAll(f)
	return string(b)
}

// ------------------------------------------------------------------ backup --

// RunNow inicia um backup (botão, bandeja ou agendador).
func (c *Core) RunNow(reason string) error {
	c.mu.Lock()
	if c.running {
		c.mu.Unlock()
		return errors.New("já existe um backup em andamento")
	}
	if c.stopping {
		c.mu.Unlock()
		return errors.New("o serviço está parando")
	}
	k := c.cfg
	if !k.Connected() {
		c.mu.Unlock()
		return errors.New("conecte ao servidor primeiro (aba Servidor)")
	}
	if len(k.Items) == 0 {
		c.mu.Unlock()
		return engine.ErrNoItems
	}
	token, err := k.Token()
	if err == nil {
		_, err = engine.ParsePublicKey(k.PublicKey)
	}
	if err != nil {
		c.mu.Unlock()
		return err
	}
	ctx, cancel := context.WithCancel(context.Background())
	c.running, c.cancel, c.done = true, cancel, make(chan struct{})
	c.progress = &engine.Progress{Phase: "preparing", Count: len(k.Items)}
	done := c.done
	c.mu.Unlock()
	c.logf("backup iniciado (%s)", reason)

	go func() {
		defer close(done)
		defer cancel()
		res := c.runBackup(ctx, k, token)
		h, err := c.store.AddRun(res)
		if err != nil {
			c.logf("não foi possível gravar o histórico: %v", err)
		}
		c.mu.Lock()
		c.hist = h
		c.running, c.cancel, c.progress = false, nil, nil
		c.mu.Unlock()
		c.scheduleNext(res)
		c.logf("backup %s: %s, %d bytes; erros: %s", res.RunName, res.Status, res.Bytes, strings.Join(res.Errors, " | "))
	}()
	return nil
}

func (c *Core) Cancel() {
	c.mu.Lock()
	if c.cancel != nil {
		c.cancel()
	}
	c.mu.Unlock()
}

func failed(msg string) engine.Result {
	now := time.Now().UTC()
	return engine.Result{StartedAt: now, FinishedAt: now, Status: "failed", Errors: []string{msg}}
}

func (c *Core) runBackup(ctx context.Context, k config.Config, token string) engine.Result {
	rcpt, _ := engine.ParsePublicKey(k.PublicKey)
	cl, err := api.New(k.ServerURL, token, userAgent(c.version))
	if err != nil {
		return failed(err.Error())
	}
	// confere o servidor antes: token válido e a MESMA chave fixada ao conectar
	h, err := cl.Hello(ctx)
	if err != nil {
		return failed("servidor indisponível ou token recusado: " + err.Error())
	}
	if engine.NormalizeFingerprint(h.PublicKeyFingerprint) != rcpt.Fingerprint {
		return failed(fmt.Sprintf("a chave GPG do servidor mudou (%s → %s): reconecte na aba Servidor depois de conferir com o administrador",
			rcpt.Fingerprint, h.PublicKeyFingerprint))
	}
	engine.SetChunkSize(h.ChunkMax)

	items := slices.Clone(k.Items)
	var snaps *vss.Set
	if k.UseVSS {
		snaps = c.snapshot(ctx, items, len(items))
		defer c.release(snaps)
		for i := range items {
			vol := vss.VolumeOf(items[i].Path)
			if src, ok := snaps.Translate(items[i].Path); ok {
				items[i].Source = src
				items[i].Note = "lido da cópia de sombra (VSS)"
			} else if why, bad := snaps.Failed[vol]; bad {
				items[i].Note = "sem cópia de sombra (" + why + "): lido ao vivo, arquivos em uso podem ter sido pulados"
				items[i].NoteWarn = true
			}
		}
	}
	return engine.Run(ctx, cl, engine.Options{
		ClientID: k.ClientID, Recipient: rcpt, Items: items, Excludes: k.Excludes, WorkDir: k.WorkDir,
		Version: "win-" + c.version, Hostname: c.hostname, OSInfo: c.osInfo,
	}, c.onProgress, c.logf)
}

// snapshot cria as cópias de sombra dos volumes locais dos itens.
func (c *Core) snapshot(ctx context.Context, items []engine.Item, count int) *vss.Set {
	seen := map[string]bool{}
	var vols []string
	for _, it := range items {
		if v := vss.VolumeOf(it.Path); v != "" && !seen[v] {
			seen[v] = true
			vols = append(vols, v)
		}
	}
	if len(vols) == 0 {
		return nil
	}
	c.onProgress(engine.Progress{Phase: "snapshot", Count: count})
	t0 := time.Now()
	set := vss.Create(ctx, vols, func(s vss.Snapshot) { c.rememberSnapshot(s, true) })
	for v, s := range set.Snaps {
		c.logf("VSS: cópia de sombra de %s criada (%s) em %s", v, s.ID, time.Since(t0).Round(time.Second))
	}
	for v, why := range set.Failed {
		c.logf("VSS: %s sem cópia de sombra: %s", v, why)
	}
	return set
}

func (c *Core) release(set *vss.Set) {
	if set == nil || len(set.Snaps) == 0 {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	if err := set.Release(ctx); err != nil {
		c.logf("VSS: falha ao apagar as cópias de sombra (nova tentativa ao reiniciar o serviço): %v", err)
		return
	}
	for _, s := range set.Snaps {
		c.rememberSnapshot(s, false)
	}
}

// rememberSnapshot guarda (ou tira) a cópia em vss.json: se o serviço cair, a próxima
// partida apaga as órfãs.
func (c *Core) rememberSnapshot(s vss.Snapshot, add bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	var list []vss.Snapshot
	if b, err := os.ReadFile(c.vssState); err == nil {
		_ = json.Unmarshal(b, &list)
	}
	list = slices.DeleteFunc(list, func(x vss.Snapshot) bool { return x.ID == s.ID })
	if add {
		list = append(list, s)
	}
	b, _ := json.Marshal(list)
	_ = os.WriteFile(c.vssState, b, 0o600)
}

func (c *Core) cleanupOrphanSnapshots() {
	var list []vss.Snapshot
	b, err := os.ReadFile(c.vssState)
	if err != nil || json.Unmarshal(b, &list) != nil || len(list) == 0 {
		return
	}
	ids := make([]string, 0, len(list))
	for _, s := range list {
		ids = append(ids, s.ID)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	if err := vss.Delete(ctx, ids); err != nil {
		c.logf("VSS: falha ao apagar cópias de sombra órfãs %v: %v", ids, err)
		return
	}
	c.logf("VSS: %d cópia(s) de sombra órfã(s) apagada(s)", len(ids))
	_ = os.Remove(c.vssState)
}

func (c *Core) onProgress(p engine.Progress) {
	c.mu.Lock()
	c.progress = &p
	c.mu.Unlock()
}

// ---------------------------------------------------------------- agenda --

// scheduleNext: depois de uma falha, tenta de novo em 1 h (se o próximo horário estiver longe).
func (c *Core) scheduleNext(r engine.Result) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	next := c.cfg.Schedule.Next(now, c.hist.LastAttempt)
	if r.Status == "failed" && c.cfg.Schedule.Mode != "manual" {
		if retry := now.Add(time.Hour); next.IsZero() || retry.Before(next) {
			next = retry
		}
	}
	c.nextRun = next
}

// Run é o laço do serviço: limpa órfãs, agenda e dispara os backups até ctx acabar.
func (c *Core) Run(ctx context.Context) {
	c.logf("serviço Pulse Backup %s iniciado (%s)", c.version, c.osInfo)
	c.cleanupOrphanSnapshots()
	c.mu.Lock()
	s, last := c.cfg.Schedule, c.hist.LastAttempt
	if s.Missed(time.Now(), last) {
		c.nextRun = time.Now().Add(2 * time.Minute) // perdeu o horário: roda logo depois de ligar
		c.logf("backup agendado perdido (último: %s): roda em 2 minutos", last.Local().Format("02/01 15:04"))
	} else {
		c.nextRun = s.Next(time.Now(), last)
	}
	c.mu.Unlock()

	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		case <-c.wake:
		}
		c.mu.Lock()
		due := !c.nextRun.IsZero() && !time.Now().Before(c.nextRun) && !c.running && !c.stopping
		ready := c.cfg.Connected() && len(c.cfg.Items) > 0
		if due && !ready {
			c.nextRun = c.cfg.Schedule.Next(time.Now(), time.Now())
		}
		c.mu.Unlock()
		if due && ready {
			if err := c.RunNow("agendado"); err != nil {
				c.logf("backup agendado não iniciou: %v", err)
			}
		}
	}
}

// Stop cancela o backup em andamento e espera ele fechar a execução (até timeout).
func (c *Core) Stop(timeout time.Duration) {
	c.mu.Lock()
	c.stopping = true
	done := c.done
	running := c.running
	if c.cancel != nil {
		c.cancel()
	}
	c.mu.Unlock()
	if running && done != nil {
		select {
		case <-done:
		case <-time.After(timeout):
			c.logf("serviço parando: o backup não terminou em %s", timeout)
		}
	}
	c.logf("serviço parado")
}

// ------------------------------------------------------------------- log --

func openLog(dir string) (string, *log.Logger, io.Closer) {
	_ = os.MkdirAll(dir, 0o700)
	path := filepath.Join(dir, "pulse-backup.log")
	if st, err := os.Stat(path); err == nil && st.Size() > 5<<20 {
		_ = os.Rename(path, path+".1") // um arquivo anterior basta
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return path, log.New(os.Stderr, "", log.LstdFlags), io.NopCloser(nil)
	}
	return path, log.New(f, "", log.LstdFlags), f
}

// Close fecha o log (depois de Stop).
func (c *Core) Close() { _ = c.logFile.Close() }
