package config

import (
	"fmt"
	"slices"
	"time"
)

// Validate confere o agendamento antes de salvar.
func (s Schedule) Validate() error {
	switch s.Mode {
	case "manual":
	case "daily":
		if _, err := time.Parse("15:04", s.Time); err != nil {
			return fmt.Errorf("horário inválido %q (use HH:MM)", s.Time)
		}
		for _, d := range s.Days {
			if d < 0 || d > 6 {
				return fmt.Errorf("dia da semana inválido: %d", d)
			}
		}
	case "interval":
		if s.IntervalHours < 1 || s.IntervalHours > 168 {
			return fmt.Errorf("intervalo deve ser de 1 a 168 horas")
		}
	default:
		return fmt.Errorf("modo de agendamento inválido: %q", s.Mode)
	}
	return nil
}

// Next devolve o próximo horário de backup depois de `after` (zero = manual).
func (s Schedule) Next(after time.Time, lastAttempt time.Time) time.Time {
	switch s.Mode {
	case "daily":
		t, err := time.Parse("15:04", s.Time)
		if err != nil {
			return time.Time{}
		}
		loc := after.Location()
		day := time.Date(after.Year(), after.Month(), after.Day(), t.Hour(), t.Minute(), 0, 0, loc)
		for i := 0; i < 8; i++ {
			cand := day.AddDate(0, 0, i)
			if !cand.After(after) {
				continue
			}
			if len(s.Days) == 0 || slices.Contains(s.Days, int(cand.Weekday())) {
				return cand
			}
		}
	case "interval":
		if lastAttempt.IsZero() {
			return after
		}
		return lastAttempt.Add(time.Duration(s.IntervalHours) * time.Hour)
	}
	return time.Time{}
}

// Missed diz se um horário agendado passou sem backup (computador desligado ou
// programa fechado) — com CatchUp, o backup roda ao abrir.
func (s Schedule) Missed(now, lastAttempt time.Time) bool {
	if !s.CatchUp || s.Mode == "manual" {
		return false
	}
	if lastAttempt.IsZero() {
		return false // primeira vez: espera o horário (o usuário pode usar "Fazer backup agora")
	}
	due := s.Next(lastAttempt, lastAttempt)
	return !due.IsZero() && !due.After(now)
}
