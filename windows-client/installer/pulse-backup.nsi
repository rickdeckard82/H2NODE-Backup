; Instalador do Pulse Backup (cliente Windows) — NSIS 3.
;
;   makensis /DVERSION=0.2.0 installer\pulse-backup.nsi
;
; Opcional: /DWEBVIEW2_BOOTSTRAPPER=<caminho do MicrosoftEdgeWebview2Setup.exe> embute o
; instalador oficial do WebView2 e o oferece onde ele falta (Windows Server). O build do
; servidor (Dockerfile) e o `make windows-installer` já passam.
;
; Instala em Program Files, registra e inicia o serviço "PulseBackup" (LocalSystem,
; início automático), abre o ícone da bandeja no login de cada usuário e cria o atalho
; no menu Iniciar. Atualizar = rodar o instalador novo por cima (para o serviço, troca o
; executável e inicia de novo; a configuração em ProgramData é mantida).

Unicode true
ManifestDPIAware true
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APP "Pulse Backup"
!define EXE "PulseBackup.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PulseBackup"
!define RUN_KEY "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APP}"
Var WebView2
OutFile "..\build\bin\PulseBackup-Setup-${VERSION}.exe"
InstallDir "$PROGRAMFILES64\PulseBackup"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
BrandingText "${APP} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "Instalador do ${APP}"
VIAddVersionKey "CompanyName" "Pulse Backup"
VIAddVersionKey "LegalCopyright" ""

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!addincludedir "${__FILEDIR__}"
!include "webview2.nsh"

!define MUI_ICON "..\build\windows\icon.ico"
!define MUI_UNICON "..\build\windows\icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Este assistente instala o ${APP} ${VERSION}.$\r$\n$\r$\nO backup roda como um serviço do Windows (mesmo sem ninguém logado), lê os arquivos de uma cópia de sombra (VSS) e envia tudo cifrado para o servidor Pulse Backup.$\r$\n$\r$\nTenha em mãos o endereço do servidor e o token gerado no painel (Servidores → Windows)."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Pulse Backup para configurar"
!define MUI_FINISHPAGE_RUN_FUNCTION OpenConfig

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "O ${APP} precisa do Windows 10 ou 11 de 64 bits."
    Abort
  ${EndIf}
  ; WebView2 (interface): já vem no Windows 10/11; no Windows Server não
  Call DetectWebView2
  StrCpy $WebView2 $0
  ${If} $WebView2 == ""
!ifdef WEBVIEW2_BOOTSTRAPPER
    MessageBox MB_ICONQUESTION|MB_YESNO "O Microsoft Edge WebView2 Runtime, usado pela janela do ${APP}, não está instalado (é o normal no Windows Server).$\r$\n$\r$\nInstalar junto agora? Ele é baixado da Microsoft (cerca de 180 MB).$\r$\n$\r$\nO serviço de backup funciona sem ele: sem o WebView2 só a janela de configuração não abre." /SD IDYES IDYES +2
      StrCpy $WebView2 "recusado"
!else
    MessageBox MB_ICONEXCLAMATION|MB_OK "Não encontrei o Microsoft Edge WebView2 Runtime, usado pela janela do ${APP}.$\r$\nO serviço de backup funciona sem ele, mas para abrir a janela instale-o em:$\r$\nhttps://developer.microsoft.com/microsoft-edge/webview2/"
!endif
  ${EndIf}
FunctionEnd

; Abre a janela de configuração já elevada (o instalador roda como administrador).
Function OpenConfig
  Exec '"$INSTDIR\${EXE}" --admin'
FunctionEnd

Section "Pulse Backup" SecMain
  SectionIn RO
  SetRegView 64
  SetShellVarContext all

  ; atualização: para o serviço e fecha as janelas/ícones abertos antes de trocar o .exe
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    DetailPrint "Parando o serviço anterior…"
    nsExec::ExecToLog '"$INSTDIR\${EXE}" service stop'
    Pop $0
  ${EndIf}
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ${EXE}'
  Pop $0
  Sleep 1000

!ifdef WEBVIEW2_BOOTSTRAPPER
  ${If} $WebView2 == ""
    DetailPrint "Instalando o Microsoft Edge WebView2 Runtime (baixando da Microsoft)…"
    InitPluginsDir
    File "/oname=$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2_BOOTSTRAPPER}"
    ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
    ${If} $1 != 0
      MessageBox MB_ICONEXCLAMATION|MB_OK "Não foi possível instalar o WebView2 (código $1). O servidor tem acesso à internet?$\r$\nO backup é instalado mesmo assim. Para a janela, instale-o depois em:$\r$\nhttps://developer.microsoft.com/microsoft-edge/webview2/" /SD IDOK
    ${EndIf}
  ${EndIf}
!endif

  SetOutPath "$INSTDIR"
  File "..\build\bin\${EXE}"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  DetailPrint "Registrando o serviço PulseBackup…"
  nsExec::ExecToLog '"$INSTDIR\${EXE}" service install'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Não foi possível registrar o serviço (código $0). Veja os detalhes da instalação."
    Abort
  ${EndIf}
  DetailPrint "Iniciando o serviço…"
  nsExec::ExecToLog '"$INSTDIR\${EXE}" service start'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION "O serviço foi instalado mas não iniciou (código $0). Inicie-o depois em Serviços (services.msc) ou pela janela do ${APP}."
  ${EndIf}

  ; ícone da bandeja no login de todos os usuários
  WriteRegStr HKLM "${RUN_KEY}" "PulseBackup" '"$INSTDIR\${EXE}" --tray'

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\${EXE}"
  CreateShortcut "$SMPROGRAMS\${APP}\Configurar (administrador).lnk" "$INSTDIR\${EXE}" "--admin"
  CreateShortcut "$SMPROGRAMS\${APP}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"

  ; Aplicativos instalados (Configurações do Windows)
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "Pulse Backup"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" 16000

  ; ícone da bandeja já agora (sem esperar o próximo login). O instalador roda elevado:
  ; quem abre o atalho é o Explorer, como o usuário logado e SEM elevação.
  CreateShortcut "$INSTDIR\Bandeja.lnk" "$INSTDIR\${EXE}" "--tray"
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\Bandeja.lnk"'
SectionEnd

Function un.onInit
  SetRegView 64
FunctionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  DetailPrint "Parando e removendo o serviço…"
  nsExec::ExecToLog '"$INSTDIR\${EXE}" service uninstall'
  Pop $0
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ${EXE}'
  Pop $0
  Sleep 1000

  DeleteRegValue HKLM "${RUN_KEY}" "PulseBackup"
  Delete "$SMPROGRAMS\${APP}\*.lnk"
  RMDir "$SMPROGRAMS\${APP}"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\Bandeja.lnk"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINST_KEY}"

  ; configuração, histórico, log e token ficam, a menos que o usuário peça (reinstalar mantém tudo)
  IfSilent keep
  ; com SetShellVarContext all, $APPDATA é C:\ProgramData
  MessageBox MB_YESNO|MB_ICONQUESTION "Apagar também a configuração, o histórico e o log ($APPDATA\PulseBackup)?$\r$\nResponda Não se for reinstalar." IDNO keep
    RMDir /r "$APPDATA\PulseBackup"
  keep:
SectionEnd
