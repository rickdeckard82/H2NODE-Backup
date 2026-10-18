; Detecta o Microsoft Edge WebView2 Runtime. Deixa em $0 a versão ("" se não achou).
; A chave oficial fica na visão de 32 bits do registro (WOW6432Node) — lida com
; SetRegView 32; conferimos também a de 64 bits, a do usuário e a pasta do runtime.
; "0.0.0.0" = desinstalado. Restaura SetRegView 64 no fim.
!define WEBVIEW2_GUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

!macro _WebView2Valid
  ${If} $0 == "0.0.0.0"
    StrCpy $0 ""
  ${EndIf}
!macroend

Function DetectWebView2
  SetRegView 32
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  !insertmacro _WebView2Valid
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
    !insertmacro _WebView2Valid
  ${EndIf}
  SetRegView 64
  ${If} $0 == ""
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
    !insertmacro _WebView2Valid
  ${EndIf}
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
    !insertmacro _WebView2Valid
  ${EndIf}
  ${If} $0 == ""
  ${AndIf} ${FileExists} "$PROGRAMFILES32\Microsoft\EdgeWebView\Application\*.*"
    StrCpy $0 "instalado"
  ${EndIf}
FunctionEnd
