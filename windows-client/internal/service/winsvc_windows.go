//go:build windows

package service

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"h2node-backup/windows-client/internal/ipc"
)

const (
	Name        = "H2nodeBackup"
	DisplayName = "H2NODE Backup"
	Description = "Backup cifrado de pastas e arquivos para o servidor H2NODE Backup (com cópias de sombra VSS)."
	// SDDL da pasta de dados: só SYSTEM e Administradores (config, token protegido, histórico, log).
	dataSDDL = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
)

// DataDir: %ProgramData%\H2nodeBackup.
func DataDir() string {
	base := os.Getenv("ProgramData")
	if base == "" {
		base = `C:\ProgramData`
	}
	return filepath.Join(base, "H2nodeBackup")
}

// protectDir cria a pasta e troca a ACL (sem herança): só SYSTEM e Administradores.
func protectDir(dir string) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	sd, err := windows.SecurityDescriptorFromString(dataSDDL)
	if err != nil {
		return err
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return err
	}
	return windows.SetNamedSecurityInfo(dir, windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil)
}

// RunService é chamado com "service run": sob o SCM vira o serviço; num console de
// administrador roda em primeiro plano (útil para diagnóstico; Ctrl+C para).
func RunService(version, osInfo string) error {
	isSvc, err := svc.IsWindowsService()
	if err != nil {
		return err
	}
	if isSvc {
		return svc.Run(Name, &handler{version: version, osInfo: osInfo})
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	fmt.Println("H2NODE Backup rodando em primeiro plano (Ctrl+C para parar). Log em", filepath.Join(DataDir(), "logs"))
	return runCore(ctx, version, osInfo, nil)
}

type handler struct{ version, osInfo string }

func (h *handler) Execute(_ []string, req <-chan svc.ChangeRequest, st chan<- svc.Status) (bool, uint32) {
	st <- svc.Status{State: svc.StartPending}
	ctx, cancel := context.WithCancel(context.Background())
	errc := make(chan error, 1)
	go func() {
		errc <- runCore(ctx, h.version, h.osInfo, func() { st <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown} })
	}()
	for {
		select {
		case err := <-errc:
			cancel()
			if err != nil {
				return true, 1
			}
			return false, 0
		case r := <-req:
			switch r.Cmd {
			case svc.Interrogate:
				st <- r.CurrentStatus
			case svc.Stop, svc.Shutdown:
				st <- svc.Status{State: svc.StopPending, WaitHint: 30000}
				cancel()
				select {
				case <-errc:
				case <-time.After(40 * time.Second):
				}
				return false, 0
			}
		}
	}
}

// migrateLegacyDataDir: a pasta de dados se chamava %ProgramData%\PulseBackup antes do
// rebranding (H2NODE Backup). O instalador já a renomeia; isto cobre quem registrou o
// serviço à mão. Só age se a pasta nova ainda não existe — nunca mistura as duas.
func migrateLegacyDataDir(dir string) {
	if _, err := os.Stat(dir); err == nil {
		return
	}
	old := filepath.Join(filepath.Dir(dir), "PulseBackup")
	if fi, err := os.Stat(old); err != nil || !fi.IsDir() {
		return
	}
	_ = os.Rename(old, dir)
}

func runCore(ctx context.Context, version, osInfo string, ready func()) error {
	dir := DataDir()
	migrateLegacyDataDir(dir)
	if err := protectDir(dir); err != nil {
		return fmt.Errorf("pasta de dados %s: %w", dir, err)
	}
	core, err := New(dir, version, osInfo)
	if err != nil {
		return err
	}
	user, err := ipc.Listen(ipc.UserPipe, ipc.UserSDDL)
	if err != nil {
		core.logf("não foi possível abrir %s: %v", ipc.UserPipe, err)
		return err
	}
	admin, err := ipc.Listen(ipc.AdminPipe, ipc.AdminSDDL)
	if err != nil {
		user.Close()
		core.logf("não foi possível abrir %s: %v", ipc.AdminPipe, err)
		return err
	}
	if ready != nil {
		ready()
	}
	go core.Serve(ctx, user, admin)
	core.Run(ctx) // até o serviço parar
	core.Stop(25 * time.Second)
	core.Close()
	return nil
}

// ----------------------------------------------------------- instalação --

// Install registra (ou atualiza) o serviço: início automático atrasado, LocalSystem,
// reinício automático em caso de falha.
func Install(exe string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("gerenciador de serviços (rode como administrador): %w", err)
	}
	defer m.Disconnect()
	cfg := mgr.Config{
		DisplayName: DisplayName, Description: Description, StartType: mgr.StartAutomatic, DelayedAutoStart: true,
		ErrorControl: mgr.ErrorNormal,
	}
	s, err := m.OpenService(Name)
	if err == nil {
		// já existe: atualiza caminho e descrição (atualização de versão)
		cur, err := s.Config()
		if err != nil {
			s.Close()
			return err
		}
		cur.BinaryPathName = fmt.Sprintf(`"%s" service run`, exe)
		cur.DisplayName, cur.Description, cur.StartType, cur.DelayedAutoStart = cfg.DisplayName, cfg.Description, cfg.StartType, true
		err = s.UpdateConfig(cur)
		if err == nil {
			err = setRecovery(s)
		}
		s.Close()
		return err
	}
	s, err = m.CreateService(Name, exe, cfg, "service", "run")
	if err != nil {
		return err
	}
	defer s.Close()
	return setRecovery(s)
}

func setRecovery(s *mgr.Service) error {
	return s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: time.Minute},
		{Type: mgr.ServiceRestart, Delay: 5 * time.Minute},
		{Type: mgr.ServiceRestart, Delay: 15 * time.Minute},
	}, uint32((24 * time.Hour).Seconds()))
}

func Uninstall() error {
	_ = Control(false)
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.OpenService(Name)
	if err != nil {
		return nil // não instalado
	}
	defer s.Close()
	return s.Delete()
}

// Control inicia (start=true) ou para o serviço e espera o novo estado.
func Control(start bool) error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("serviço %s não instalado", Name)
	}
	defer s.Close()
	want := svc.Stopped
	if start {
		want = svc.Running
		if err := s.Start(); err != nil && !errors.Is(err, windows.ERROR_SERVICE_ALREADY_RUNNING) {
			return err
		}
	} else if _, err := s.Control(svc.Stop); err != nil && !errors.Is(err, windows.ERROR_SERVICE_NOT_ACTIVE) {
		return err
	}
	deadline := time.Now().Add(60 * time.Second)
	for time.Now().Before(deadline) {
		q, err := s.Query()
		if err != nil {
			return err
		}
		if q.State == want {
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("o serviço não chegou ao estado esperado em 60 s")
}
