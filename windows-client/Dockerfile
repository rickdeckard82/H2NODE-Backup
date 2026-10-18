# Compila o instalador do cliente Windows (PulseBackup-Setup-<versão>.exe) num Linux,
# sem Windows: Go cruzado (sem cgo) + Wails + NSIS. Usado pelo serviço client-builder do
# docker-compose: a cada `docker compose build` o Docker só recompila se algo em
# windows-client/ mudou, e na subida o instalador vai para o volume que o backend
# publica na página Downloads.

FROM golang:1.27-bookworm AS build
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update && apt-get install -y --no-install-recommends nsis \
 && rm -rf /var/lib/apt/lists/*
RUN go install github.com/wailsapp/wails/v2/cmd/wails@v2.17.0
# Instalador oficial (bootstrapper) do WebView2, oferecido onde ele falta (Windows Server)
RUN curl -fsSL -o /opt/MicrosoftEdgeWebview2Setup.exe "https://go.microsoft.com/fwlink/p/?LinkId=2124703" \
 && test "$(head -c 2 /opt/MicrosoftEdgeWebview2Setup.exe)" = "MZ"

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY . .
# bindings (frontend/wailsjs) já estão no repositório: gerá-los exigiria rodar o app no Linux
RUN cd frontend && npm run build \
 && cd .. && wails build -s -m -skipbindings -clean -trimpath -platform windows/amd64 \
 && VERSION=$(sed -n 's/^var Version = "\([0-9.]*\)"/\1/p' main.go) \
 && test -n "$VERSION" \
 && makensis -V2 -DVERSION="$VERSION" -DWEBVIEW2_BOOTSTRAPPER=/opt/MicrosoftEdgeWebview2Setup.exe installer/pulse-backup.nsi \
 && mkdir /dist && cp build/bin/PulseBackup-Setup-*.exe /dist/ \
 && cd /dist && sha256sum *.exe

FROM busybox:1.37
COPY --from=build /dist/ /dist/
# troca o instalador do volume de uma vez (sem o backend ver arquivo pela metade)
CMD ["sh", "-c", "set -e; for f in /dist/*.exe; do cp \"$f\" \"/out/.$(basename \"$f\").tmp\"; done; rm -f /out/*.exe; for f in /out/.*.tmp; do n=$(basename \"$f\" .tmp); mv \"$f\" \"/out/${n#.}\"; done; ls -l /out"]
