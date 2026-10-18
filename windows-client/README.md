# Pulse Backup — cliente Windows

Aplicativo (Go + [Wails v2](https://wails.io)) com interface e ícone na bandeja: escolhe
pastas e arquivos, agenda, cifra no próprio computador com a chave pública GPG do
servidor e envia por HTTPS (`/api/agent/v1`). Passo a passo de uso no painel em
**Ajuda → Windows**.

## Gerar o executável

Requisitos: Go 1.24+, Node 20+, Wails CLI v2 (`go install github.com/wailsapp/wails/v2/cmd/wails@v2.17.0`).

```bash
cd windows-client
wails build -clean -trimpath          # -> build/bin/PulseBackup.exe
```

Também compila a partir do Linux (`wails build -platform windows/amd64`), sem CGO.
O `build/appicon.png` (ícone do .exe) é gerado por `go run ./tools/genicon`.

## Testes

```bash
go test ./...                          # motor (tar+gzip+OpenPGP+envio com retomada), agendador, DPAPI
cd frontend && npm ci && npx tsc --noEmit && npx eslint . --max-warnings 0
```

Para revisar a interface no navegador sem o Go: `cd frontend && npm run dev` (o
`src/devmock.ts` simula o backend; `?connected=0` e `?running=1` mudam o estado).

## Estrutura

- `main.go` / `app.go` — janela, métodos chamados pela interface, agendador, log.
- `tray.go` — ícone da bandeja (`fyne.io/systray`, numa thread própria).
- `internal/engine` — o backup: pasta → tar → gzip → OpenPGP → arquivo na pasta de
  trabalho → envio → apaga; manifesto `pulse-backup/1` (o mesmo do agente Linux).
- `internal/api` — HTTPS com token, pedaços de até 32 MiB, retomada pelo tamanho que o
  servidor já tem.
- `internal/config` — `%APPDATA%\PulseBackup\config.json` e `history.json`; token
  protegido com DPAPI; agendamento.
- `frontend/` — React + Tailwind no padrão visual do painel.

## Segurança

- Nada em claro vai para o disco: só o `.gpg` de um item por vez fica na pasta de
  trabalho (`%LOCALAPPDATA%\PulseBackup\work`), apagado após o envio. Os arquivos de
  origem só são lidos.
- A chave pública é **fixada** na conexão (o usuário confere a impressão digital com a
  do painel). Se o servidor anunciar outra, o backup para em vez de cifrar para ela.
- O token só envia (não lista, não lê, não apaga) e fica protegido por DPAPI.
- Versão: suba `Version` em `main.go` e `productVersion` em `wails.json` a cada mudança.
