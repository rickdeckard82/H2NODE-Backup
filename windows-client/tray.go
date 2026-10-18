package main

import (
	"fmt"
	goruntime "runtime"
	"sync"
	"time"

	"fyne.io/systray"

	"pulse-backup/windows-client/internal/icon"
)

// tray: ícone na bandeja. Roda numa thread própria do sistema (systray cria a janela
// oculta e o laço de mensagens nela), separada do laço do Wails.
type tray struct {
	mu       sync.Mutex
	ready    bool
	state    string // "" | running | failed
	open     *systray.MenuItem
	runNow   *systray.MenuItem
	cancel   *systray.MenuItem
	statusMI *systray.MenuItem
}

var trayOnce sync.Once

func startTray(a *App) *tray {
	t := &tray{}
	ready := make(chan struct{})
	go func() {
		goruntime.LockOSThread()
		systray.Run(func() {
			systray.SetIcon(icon.ICO(32, ""))
			systray.SetTitle("Pulse Backup")
			systray.SetTooltip("Pulse Backup")
			t.statusMI = systray.AddMenuItem("Pulse Backup", "")
			t.statusMI.Disable()
			systray.AddSeparator()
			t.open = systray.AddMenuItem("Abrir", "Abrir a janela do Pulse Backup")
			t.runNow = systray.AddMenuItem("Fazer backup agora", "")
			t.cancel = systray.AddMenuItem("Cancelar backup", "")
			t.cancel.Disable()
			systray.AddSeparator()
			quit := systray.AddMenuItem("Sair", "Encerra o Pulse Backup (o backup agendado deixa de rodar)")
			systray.SetOnTapped(a.ShowWindow) // clique no ícone abre a janela
			t.mu.Lock()
			t.ready = true
			t.mu.Unlock()
			close(ready)
			go func() {
				for {
					select {
					case <-t.open.ClickedCh:
						a.ShowWindow()
					case <-t.runNow.ClickedCh:
						if err := a.RunNow(); err != nil {
							a.logf("bandeja: %v", err)
							a.ShowWindow()
						}
					case <-t.cancel.ClickedCh:
						a.Cancel()
					case <-quit.ClickedCh:
						a.Quit()
						return
					}
				}
			}()
		}, func() {})
	}()
	select {
	case <-ready:
	case <-time.After(5 * time.Second):
		a.logf("ícone da bandeja não iniciou")
	}
	return t
}

func stopTray() { trayOnce.Do(systray.Quit) }

// update reflete o estado no ícone, na dica e no menu.
func (t *tray) update(st UIState) {
	if t == nil {
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if !t.ready {
		return
	}
	state, tip := "", "Pulse Backup"
	switch {
	case st.Running:
		state = "running"
		tip = "Pulse Backup — backup em andamento"
		if p := st.Progress; p != nil && p.Count > 0 {
			tip = fmt.Sprintf("Pulse Backup — backup em andamento (%d de %d)", max(p.Index, 1), p.Count)
		}
	case len(st.History) > 0 && st.History[0].Status == "failed":
		state = "failed"
		tip = "Pulse Backup — o último backup falhou"
	case st.LastSuccess != "":
		if ts, err := time.Parse(time.RFC3339, st.LastSuccess); err == nil {
			tip = "Pulse Backup — último backup: " + ts.Local().Format("02/01 15:04")
		}
	}
	if !st.Connected {
		tip = "Pulse Backup — não conectado ao servidor"
	}
	if state != t.state {
		systray.SetIcon(icon.ICO(32, state))
		t.state = state
	}
	systray.SetTooltip(tip)
	t.statusMI.SetTitle(tip)
	if st.Running {
		t.runNow.Disable()
		t.cancel.Enable()
	} else {
		t.runNow.Enable()
		t.cancel.Disable()
	}
}
