; Sreon for Windows - installer built with NSIS 3 (MUI2).
;
; tools/build.py compiles this with absolute paths, so nothing depends on the
; working directory makensis happens to run from:
;
;   makensis -DVERSION=0.5.1
;            -DSOURCE_DIR=C:\w\dist\Sreon   -DSOURCE_GLOB=C:\w\dist\Sreon\*.*
;            -DICON=C:\w\assets\icon.ico
;            -DHEADER_BMP=C:\w\nsis\header.bmp  -DWELCOME_BMP=C:\w\nsis\welcome.bmp
;            -DGUIDE=C:\repo\If-it-says-unverified.txt
;            -DOUTFILE=C:\w\dist\SreonSetup.exe  Sreon.nsi
;
; The fallbacks below let "makensis Sreon.nsi" run by hand from this folder: a bare
; filename is resolved against the folder of the script being compiled, which behaves the
; same on every platform. tools/build.py passes absolute HEADER_BMP/WELCOME_BMP/SOURCE_GLOB
; written with the host separator, because MUI adds the wizard bitmaps with "File" and that
; goes through NSIS' own path search - the one place a separator guess actually breaks.

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SOURCE_DIR
  !define SOURCE_DIR "../../dist/Sreon"
!endif
!ifndef ICON
  !define ICON "../../assets/icon.ico"
!endif
!ifndef GUIDE
  !define GUIDE "../../../If-it-says-unverified.txt"
!endif
; The payload glob comes from the caller so this script never has to guess a path separator.
!ifndef SOURCE_GLOB
  !define SOURCE_GLOB "${SOURCE_DIR}/*.*"
!endif
!ifndef OUTFILE
  !define OUTFILE "SreonSetup.exe"
!endif
; Artwork: absolute paths from the build, otherwise next to this script.
!ifndef HEADER_BMP
  !define HEADER_BMP "header.bmp"
!endif
!ifndef WELCOME_BMP
  !define WELCOME_BMP "welcome.bmp"
!endif

!define APPNAME "Sreon"
!define PUBLISHER "Sreon"
!define EXE "Sreon.exe"
!define RUNKEY "Software\${APPNAME}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Unicode true
Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "${RUNKEY}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails nevershow
ShowUninstDetails nevershow
BrandingText " "

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinVer.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"

; ----------------------------------------------------------------- appearance
!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${HEADER_BMP}"
!define MUI_HEADERIMAGE_UNBITMAP "${HEADER_BMP}"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${WELCOME_BMP}"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Sreon is not installed yet. Cancel anyway?"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "Sreon installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Free and open source - no warranty"
VIAddVersionKey /LANG=1033 "OriginalFilename" "SreonSetup.exe"

; ----------------------------------------------------------------------- pages
!define MUI_WELCOMEPAGE_TITLE "Welcome to the Sreon installer"
!define MUI_WELCOMEPAGE_TEXT "Sreon is a native desktop browser with its own search front-end - search privately, browse freely, no account and no telemetry.$\r$\n$\r$\nIt needs about 320 MB and adds Sreon to your Start Menu.$\r$\n$\r$\nWindows may say “app isn't commonly signed” the first time you open it, because this build is not publisher-signed. That warning is about the signature, not a virus finding: click More info, then Run anyway.$\r$\n$\r$\nVersion ${VERSION}, 64-bit."
!insertmacro MUI_PAGE_WELCOME

!define MUI_PAGE_HEADER_TEXT "Where to install"
!define MUI_PAGE_HEADER_SUBTEXT "Sreon needs about 320 MB."
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Open Sreon now"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\If-it-says-unverified.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the “can't be opened” guide"
!define MUI_FINISHPAGE_LINK "Show me the installed files"
!define MUI_FINISHPAGE_LINK_LOCATION "$INSTDIR"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------- sections
LangString DESC_APP        ${LANG_ENGLISH} "The browser itself. Required."
LangString DESC_STARTMENU  ${LANG_ENGLISH} "Sreon in the Start Menu, so it shows up in your Apps list and search."
LangString DESC_DESKTOP    ${LANG_ENGLISH} "Also put an icon on the Desktop."
LangString DESC_BROWSERLIST ${LANG_ENGLISH} "Offer Sreon in Settings > Apps > Default browser. Nothing becomes your default unless you pick it."

Section "!Sreon" SecApp
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_GLOB}"
  ; NSIS /oname takes a single unquoted token, so the guide keeps its hyphenated name.
  File /oname=If-it-says-unverified.txt "${GUIDE}"

  ; The upgrade hint first, in the default view: InstallDirRegKey is read by the directory
  ; page, and makensis is 32-bit, so that read looks in WOW6432Node.
  WriteRegStr HKLM "${RUNKEY}" "InstallDir" "$INSTDIR"

  ; Sreon is a 64-bit program, so its own entries belong in the 64-bit view. SetRegView is
  ; only legal inside a Section or a Function - putting it at the top of the file is an error.
  SetRegView 64
  WriteRegStr HKLM "${RUNKEY}" "Version" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\${EXE},0"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKLM "${UNINSTKEY}" "HelpLink" "https://github.com/FellowPythonCoder/sreoncode"
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  ${If} $0 > 0
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" "$0"
  ${EndIf}
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Sreon in Start Menu" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  CreateShortCut "$SMPROGRAMS\${APPNAME}\If Sreon cant be opened.lnk" "$INSTDIR\If-it-says-unverified.txt"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
SectionEnd

Section "Add to Windows' browser list" SecBrowserList
  SetRegView 64
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}" "" "${APPNAME}"
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}\Capabilities" "ApplicationName" "${APPNAME}"
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}\Capabilities" "ApplicationDescription" "Search privately. Browse freely."
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}\Capabilities\StartMenuInternet" "${APPNAME}" "Web Browser"
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}\DefaultIcon" "" "$INSTDIR\${EXE},0"
  WriteRegStr HKLM "Software\Clients\StartMenuInternet\${APPNAME}\shell\open\command" "" '"$INSTDIR\${EXE}" "%1"'
SectionEnd

; Hover text for the components page. MUI builds these into one if/elseif chain, so the
; block has to be wrapped - a bare MUI_DESCRIPTION_TEXT expands to ${elseif} and makensis
; aborts with "Cannot use Else without a preceding If".
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "$(DESC_APP)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "$(DESC_STARTMENU)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "$(DESC_DESKTOP)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecBrowserList} "$(DESC_BROWSERLIST)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ----------------------------------------------------------------- uninstall
Section "Uninstall"
  DeleteRegKey HKLM "${RUNKEY}"   ; the 32-bit-view upgrade hint, gone before the switch
  SetRegView 64
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\If Sreon cant be opened.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  DeleteRegKey HKLM "Software\Clients\StartMenuInternet\${APPNAME}"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "${RUNKEY}"   ; 64-bit view (the 32-bit one was removed above)
  RMDir /r "$INSTDIR"
  ; Your settings live in %APPDATA%\Sreon so a reinstall can bring the vault back.
  ; They are only removed if you say so here.
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your Sreon profile (theme, vault, bookmarks) from$\r$\n$APPDATA\Sreon?" IDYES wipe
  Goto done
  wipe:
    RMDir /r "$APPDATA\Sreon"
  done:
SectionEnd

; ------------------------------------------------------------------- checks
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Sreon needs 64-bit Windows."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Sreon needs Windows 10 or newer: Qt WebEngine dropped Windows 7 and 8."
    Abort
  ${EndIf}
FunctionEnd
