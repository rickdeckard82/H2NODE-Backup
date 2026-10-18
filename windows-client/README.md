# Pulse Backup — cliente Windows

Serviço do Windows + interface (Go + [Wails v2](https://wails.io)): agenda e faz o backup
de pastas e arquivos lendo de uma **cópia de sombra (VSS)**, cifra no próprio computador
com a chave pública GPG do servidor e envia por HTTPS (`/api/agent/v1`). Passo a passo de
uso no painel em **Ajuda → Windows**.

## Arquitetura

Um único `PulseBackup.exe` com três papéis:

| Comando | Papel |
|---|---|
| `PulseBackup.exe service run` | **Serviço** “PulseBackup” (LocalSystem, início automático atrasado, reinicia sozinho se cair). Agenda, cria as cópias de sombra, faz e envia os backups. Configuração, histórico e log em `%ProgramData%\PulseBackup` (ACL: só SYSTEM e Administradores); token protegido com DPAPI da conta SYSTEM. |
| `PulseBackup.exe --tray` | **Ícone na bandeja** de cada usuário (aberto no login pelo `HKLM\…\Run`): estado, “fazer backup agora”, cancelar, histórico e log. |
| `PulseBackup.exe --admin` | **Janela de configuração** elevada (UAC): pastas, servidor/token, agendamento, VSS. |

A interface fala com o serviço por named pipes locais (HTTP/JSON): `\\.\pipe\PulseBackup`
(usuários interativos: ler o estado, pedir backup, cancelar, ver o log) e
`\\.\pipe\PulseBackupAdmin` (só Administradores elevados e SYSTEM: mudar a configuração).
Os dois negam acesso pela rede.

Também: `service install|uninstall|start|stop` (usados pelo instalador, como administrador).

### VSS

Antes do backup, uma cópia de sombra por volume local NTFS/ReFS envolvido
(`Win32_ShadowCopy.Create`, contexto `ClientAccessible`, via PowerShell). Os arquivos são
lidos por `\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\…` (sem montar letra de
unidade). A cópia é apagada no fim; as que sobrarem (serviço derrubado no meio) ficam em
`vss.json` e são apagadas na próxima partida. Sem VSS (pendrive, rede, falha), lê ao vivo
e marca o item como aviso.

## Gerar

**No servidor do painel é automático.** O serviço `client-builder` do `docker-compose.yml`
compila com o `Dockerfile` desta pasta (Go + Wails + NSIS no Linux, sem Windows) a cada
`docker compose build` em que algo aqui mudou, e o instalador aparece sozinho na página
**Downloads**. Para publicar uma versão nova: suba a versão (abaixo), faça o commit e, no
servidor, `git pull && docker compose build && docker compose up -d`.

Versão (as três iguais): `Version` em `main.go`, `productVersion` em `wails.json` e
`version` em `frontend/package.json` — ela vai no nome do instalador e no painel.

À mão, para desenvolver: Go 1.24+, Node 20+, Wails CLI v2
(`go install github.com/wailsapp/wails/v2/cmd/wails@v2.17.0`) e NSIS 3 (`makensis`).

```bash
make windows-installer        # na raiz: wails build + makensis
# -> windows-client/build/bin/PulseBackup.exe e PulseBackup-Setup-<versão>.exe
```

O instalador embute o bootstrapper oficial do **WebView2** (`MicrosoftEdgeWebview2Setup.exe`,
baixado no build) e, onde o runtime falta (Windows Server), pergunta se instala junto.
Não é assinado (SmartScreen avisa “editor desconhecido”).

## Testes

```bash
go test ./...      # motor (tar+gzip+OpenPGP+envio com retomada), leitura por caminho de dispositivo
                   # (o mesmo do VSS), pipes reais (configurar → backup), agendador, DPAPI
cd frontend && npm ci && npx tsc --noEmit && npx eslint . --max-warnings 0
```

Criar cópias de sombra e instalar o serviço exigem administrador: teste à mão numa máquina
de testes (instale, conecte, “Fazer backup agora” com um `.xlsx` aberto no Excel, confira
“lido da cópia de sombra (VSS)” no histórico e `vssadmin list shadows` vazio no fim).

Para revisar a interface no navegador sem o Go: `cd frontend && npm run dev`
(`src/devmock.ts` simula o serviço; `?admin=0`, `?service=0`, `?connected=0` e `?running=1`).

## Estrutura

- `main.go` (papéis), `app.go` (interface: cliente dos pipes), `tray.go` (bandeja), `platform_windows.go` (UAC, versão do Windows).
- `internal/service` — núcleo do serviço: agenda, backup com VSS, estado, rotas dos pipes, SCM (instalar/rodar).
- `internal/vss` — cópias de sombra e tradução de caminhos.
- `internal/ipc` — named pipes (SDDL) e cliente HTTP sobre eles.
- `internal/engine` — o backup: pasta → tar → gzip → OpenPGP → pasta de trabalho → envio → apaga; manifesto `pulse-backup/1`.
- `internal/api` — HTTPS com token, pedaços de até 32 MiB, retomada.
- `internal/config` — `config.json`/`history.json`, DPAPI, agendamento.
- `installer/pulse-backup.nsi` — instalador NSIS. `frontend/` — React + Tailwind no padrão do painel.

## Segurança

- Nada em claro vai para o disco: só o `.gpg` de um item por vez na pasta de trabalho, apagado após o envio. Os arquivos de origem só são lidos.
- A chave pública é **fixada** na conexão (o administrador confere a impressão digital com a do painel). Se o servidor anunciar outra, o backup para.
- O token só envia (não lista, não lê, não apaga), fica só no serviço (DPAPI da conta SYSTEM) e nunca volta para a interface.
- Versão: suba `Version` em `main.go`, `productVersion` em `wails.json` e `version` em `frontend/package.json`.
