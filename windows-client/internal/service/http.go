package service

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"time"

	"h2node-backup/windows-client/internal/config"
	"h2node-backup/windows-client/internal/engine"
)

// Rotas do pipe de usuários: ver o estado, fazer backup agora, cancelar, ler o log.
// O pipe de administradores tem estas e mais as que mudam a configuração.

func reply(w http.ResponseWriter, v any, err error) {
	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	if v == nil {
		v = map[string]bool{"ok": true}
	}
	_ = json.NewEncoder(w).Encode(v)
}

func decode[T any](r *http.Request) (T, error) {
	var v T
	err := json.NewDecoder(http.MaxBytesReader(nil, r.Body, 1<<20)).Decode(&v)
	if err != nil {
		err = errors.New("pedido inválido: " + err.Error())
	}
	return v, err
}

func (c *Core) userMux() *http.ServeMux {
	m := http.NewServeMux()
	m.HandleFunc("GET /state", func(w http.ResponseWriter, _ *http.Request) { reply(w, c.State(), nil) })
	m.HandleFunc("POST /run", func(w http.ResponseWriter, _ *http.Request) { reply(w, nil, c.RunNow("manual")) })
	m.HandleFunc("POST /cancel", func(w http.ResponseWriter, _ *http.Request) { c.Cancel(); reply(w, nil, nil) })
	m.HandleFunc("GET /log", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte(c.LogTail(256 << 10)))
	})
	return m
}

func (c *Core) adminMux() *http.ServeMux {
	m := c.userMux()
	m.HandleFunc("POST /connect/test", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[struct{ URL, Token string }](r)
		if err != nil {
			reply(w, nil, err)
			return
		}
		info, err := c.TestConnection(r.Context(), in.URL, in.Token)
		reply(w, info, err)
	})
	m.HandleFunc("POST /connect/confirm", func(w http.ResponseWriter, _ *http.Request) { reply(w, nil, c.ConfirmConnection()) })
	m.HandleFunc("POST /disconnect", func(w http.ResponseWriter, _ *http.Request) { reply(w, nil, c.Disconnect()) })
	m.HandleFunc("POST /items/add", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[[]engine.Item](r)
		if err == nil {
			err = c.AddItems(in)
		}
		reply(w, nil, err)
	})
	m.HandleFunc("POST /items/remove", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[struct{ Path string }](r)
		if err == nil {
			err = c.RemoveItem(in.Path)
		}
		reply(w, nil, err)
	})
	m.HandleFunc("POST /excludes", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[[]string](r)
		if err == nil {
			err = c.SetExcludes(in)
		}
		reply(w, nil, err)
	})
	m.HandleFunc("POST /schedule", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[config.Schedule](r)
		if err == nil {
			err = c.SetSchedule(in)
		}
		reply(w, nil, err)
	})
	m.HandleFunc("POST /workdir", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[struct{ Dir string }](r)
		if err == nil {
			err = c.SetWorkDir(in.Dir)
		}
		reply(w, nil, err)
	})
	m.HandleFunc("POST /vss", func(w http.ResponseWriter, r *http.Request) {
		in, err := decode[struct{ Enabled bool }](r)
		if err == nil {
			err = c.SetVSS(in.Enabled)
		}
		reply(w, nil, err)
	})
	return m
}

// Serve atende os dois listeners até ctx acabar.
func (c *Core) Serve(ctx context.Context, user, admin net.Listener) {
	srvs := []*http.Server{
		{Handler: c.userMux(), ReadHeaderTimeout: 10 * time.Second},
		{Handler: c.adminMux(), ReadHeaderTimeout: 10 * time.Second},
	}
	for i, l := range []net.Listener{user, admin} {
		go func() {
			if err := srvs[i].Serve(l); err != nil && !errors.Is(err, http.ErrServerClosed) {
				c.logf("pipe %s: %v", l.Addr(), err)
			}
		}()
	}
	<-ctx.Done()
	sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for _, s := range srvs {
		_ = s.Shutdown(sctx)
	}
}
