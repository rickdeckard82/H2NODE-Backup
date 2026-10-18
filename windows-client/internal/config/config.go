// Package config guarda a configuração e o histórico do cliente em
// %APPDATA%\PulseBackup (por usuário do Windows). O token de envio fica protegido
// com DPAPI: só este usuário, nesta máquina, consegue decifrá-lo.
package config

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"pulse-backup/windows-client/internal/engine"
)

// Schedule: quando o backup roda sozinho.
type Schedule struct {
	Mode          string `json:"mode"`           // daily | interval | manual
	Time          string `json:"time"`           // HH:MM (daily)
	Days          []int  `json:"days"`           // 0=domingo … 6=sábado (daily); vazio = todos
	IntervalHours int    `json:"interval_hours"` // interval
	CatchUp       bool   `json:"catch_up"`       // computador desligado no horário: roda ao ligar
}

// Config é o que o usuário escolhe na interface.
type Config struct {
	ServerURL        string        `json:"server_url"`
	TokenProtected   string        `json:"token_protected"` // DPAPI, base64
	ClientID         string        `json:"client_id"`
	ClientName       string        `json:"client_name"`
	PublicKey        string        `json:"public_key"` // chave fixada ao conectar (não muda sozinha)
	Fingerprint      string        `json:"fingerprint"`
	Items            []engine.Item `json:"items"`
	Excludes         []string      `json:"excludes"`
	Schedule         Schedule      `json:"schedule"`
	WorkDir          string        `json:"work_dir"`
	StartWithWindows bool          `json:"start_with_windows"`
}

// DefaultExcludes: temporários do Office, do Windows e de navegadores.
var DefaultExcludes = []string{"~$*", "*.tmp", "Thumbs.db", "desktop.ini", "$RECYCLE.BIN", "System Volume Information"}

// History é o estado guardado entre execuções.
type History struct {
	LastSuccess time.Time       `json:"last_success"`
	LastAttempt time.Time       `json:"last_attempt"`
	Runs        []engine.Result `json:"runs"` // mais recente primeiro
}

const historyMax = 50

// Store lê e grava os arquivos de configuração (com trava: a interface e o agendador usam juntos).
type Store struct {
	mu  sync.Mutex
	dir string
}

// Dirs: configuração em %APPDATA%, dados descartáveis (trabalho, log) em %LOCALAPPDATA%.
func AppDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(base, "PulseBackup"), nil
}

func LocalDir() string {
	if base, err := os.UserCacheDir(); err == nil { // %LOCALAPPDATA%
		return filepath.Join(base, "PulseBackup")
	}
	return filepath.Join(os.TempDir(), "PulseBackup")
}

func NewStore(dir string) (*Store, error) {
	if dir == "" {
		d, err := AppDir()
		if err != nil {
			return nil, err
		}
		dir = d
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	return &Store{dir: dir}, nil
}

func (s *Store) Dir() string { return s.dir }

func defaults() Config {
	return Config{
		Excludes: append([]string(nil), DefaultExcludes...),
		Schedule: Schedule{Mode: "daily", Time: "12:30", CatchUp: true},
		WorkDir:  filepath.Join(LocalDir(), "work"),
	}
}

func readJSON(path string, v any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, v)
}

// writeJSON grava num temporário e renomeia: nunca deixa o arquivo pela metade.
func writeJSON(path string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func (s *Store) Load() (Config, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := defaults()
	err := readJSON(filepath.Join(s.dir, "config.json"), &c)
	if errors.Is(err, os.ErrNotExist) {
		return defaults(), nil
	}
	if c.WorkDir == "" {
		c.WorkDir = defaults().WorkDir
	}
	return c, err
}

func (s *Store) Save(c Config) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return writeJSON(filepath.Join(s.dir, "config.json"), c)
}

func (s *Store) LoadHistory() History {
	s.mu.Lock()
	defer s.mu.Unlock()
	var h History
	_ = readJSON(filepath.Join(s.dir, "history.json"), &h)
	return h
}

// AddRun registra uma execução no histórico.
func (s *Store) AddRun(r engine.Result) (History, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var h History
	_ = readJSON(filepath.Join(s.dir, "history.json"), &h)
	h.LastAttempt = r.FinishedAt
	if r.Status == "success" || r.Status == "partial" {
		h.LastSuccess = r.FinishedAt
	}
	h.Runs = append([]engine.Result{r}, h.Runs...)
	if len(h.Runs) > historyMax {
		h.Runs = h.Runs[:historyMax]
	}
	return h, writeJSON(filepath.Join(s.dir, "history.json"), h)
}

// SetToken protege o token com DPAPI antes de guardar.
func (c *Config) SetToken(token string) error {
	if token == "" {
		c.TokenProtected = ""
		return nil
	}
	enc, err := protect([]byte(token))
	if err != nil {
		return fmt.Errorf("não foi possível proteger o token: %w", err)
	}
	c.TokenProtected = base64.StdEncoding.EncodeToString(enc)
	return nil
}

func (c *Config) Token() (string, error) {
	if c.TokenProtected == "" {
		return "", errors.New("cliente não conectado ao servidor")
	}
	raw, err := base64.StdEncoding.DecodeString(c.TokenProtected)
	if err != nil {
		return "", err
	}
	plain, err := unprotect(raw)
	if err != nil {
		return "", fmt.Errorf("não foi possível ler o token (outro usuário do Windows?): %w", err)
	}
	return string(plain), nil
}

// Connected: tem servidor, token e chave fixada.
func (c *Config) Connected() bool {
	return c.ServerURL != "" && c.TokenProtected != "" && c.PublicKey != ""
}
