package config

import (
	"testing"
	"time"

	"pulse-backup/windows-client/internal/engine"
)

func TestScheduleNextDaily(t *testing.T) {
	loc := time.Local
	s := Schedule{Mode: "daily", Time: "12:30"}
	// quinta 10:00 -> quinta 12:30
	now := time.Date(2026, 10, 15, 10, 0, 0, 0, loc)
	if got := s.Next(now, time.Time{}); !got.Equal(time.Date(2026, 10, 15, 12, 30, 0, 0, loc)) {
		t.Fatalf("next = %v", got)
	}
	// quinta 13:00 -> sexta 12:30
	now = time.Date(2026, 10, 15, 13, 0, 0, 0, loc)
	if got := s.Next(now, time.Time{}); !got.Equal(time.Date(2026, 10, 16, 12, 30, 0, 0, loc)) {
		t.Fatalf("next = %v", got)
	}
	// só dias úteis: sexta 13:00 -> segunda 12:30
	s.Days = []int{1, 2, 3, 4, 5}
	now = time.Date(2026, 10, 16, 13, 0, 0, 0, loc)
	if got := s.Next(now, time.Time{}); !got.Equal(time.Date(2026, 10, 19, 12, 30, 0, 0, loc)) {
		t.Fatalf("next = %v (%s)", got, got.Weekday())
	}
}

func TestScheduleIntervalAndMissed(t *testing.T) {
	now := time.Date(2026, 10, 18, 9, 0, 0, 0, time.Local)
	s := Schedule{Mode: "interval", IntervalHours: 6, CatchUp: true}
	last := now.Add(-2 * time.Hour)
	if got := s.Next(now, last); !got.Equal(last.Add(6 * time.Hour)) {
		t.Fatalf("next = %v", got)
	}
	if s.Missed(now, last) {
		t.Fatal("não perdeu: o próximo ainda não chegou")
	}
	if !s.Missed(now, now.Add(-7*time.Hour)) {
		t.Fatal("deveria ter perdido (último há 7 h, intervalo 6 h)")
	}
	// diário: computador desligado ontem às 12:30 -> perdeu
	d := Schedule{Mode: "daily", Time: "12:30", CatchUp: true}
	if !d.Missed(now, time.Date(2026, 10, 16, 12, 31, 0, 0, time.Local)) {
		t.Fatal("deveria acusar o backup de ontem como perdido")
	}
	d.CatchUp = false
	if d.Missed(now, time.Date(2026, 10, 16, 12, 31, 0, 0, time.Local)) {
		t.Fatal("sem catch_up nunca acusa perdido")
	}
	if (Schedule{Mode: "manual"}).Next(now, last) != (time.Time{}) {
		t.Fatal("manual não agenda")
	}
}

func TestValidate(t *testing.T) {
	bad := []Schedule{{Mode: "daily", Time: "25:00"}, {Mode: "daily", Time: "08:00", Days: []int{7}},
		{Mode: "interval", IntervalHours: 0}, {Mode: "x"}}
	for _, s := range bad {
		if s.Validate() == nil {
			t.Fatalf("deveria recusar %+v", s)
		}
	}
	if (Schedule{Mode: "daily", Time: "08:05", Days: []int{1, 5}}).Validate() != nil {
		t.Fatal("agendamento válido recusado")
	}
}

func TestStoreTokenAndHistory(t *testing.T) {
	st, err := NewStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	c, _ := st.Load()
	if c.Schedule.Mode != "daily" || len(c.Excludes) == 0 {
		t.Fatalf("padrões não aplicados: %+v", c)
	}
	if err := c.SetToken("pbu_segredo"); err != nil {
		t.Fatal(err)
	}
	if c.TokenProtected == "" || c.TokenProtected == "pbu_segredo" {
		t.Fatal("token não protegido")
	}
	if err := st.Save(c); err != nil {
		t.Fatal(err)
	}
	c2, _ := st.Load()
	if tok, err := c2.Token(); err != nil || tok != "pbu_segredo" {
		t.Fatalf("token lido = %q, %v", tok, err)
	}
	for i := 0; i < historyMax+5; i++ {
		st.AddRun(engine.Result{Status: "success", FinishedAt: time.Now()})
	}
	h, _ := st.AddRun(engine.Result{Status: "failed", FinishedAt: time.Now()})
	if len(h.Runs) != historyMax || h.Runs[0].Status != "failed" || h.LastSuccess.IsZero() {
		t.Fatalf("histórico inesperado: %d runs", len(h.Runs))
	}
}
