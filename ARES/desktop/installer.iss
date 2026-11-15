; ARES Windows installer (Inno Setup 6 - https://jrsoftware.org/isinfo.php)
; Built by desktop\build_windows.bat after PyInstaller has produced dist\ARES\ARES.exe.
; Result: dist\installer\ARES-Setup-0.5.0.exe  - works fully offline, needs no Python / Node.js / admin rights.

#define AppName "ARES"
#define AppVersion "0.5.0"
#define AppPublisher "Team ARES - NASA Space Apps Challenge 2026"
#define AppExe "ARES.exe"
#define Root ".."

[Setup]
AppId={{6B3E3A52-7C1D-4E5B-9A0F-2026A4E50001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments=Astronaut health monitoring and emergency decision support (research prototype)
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#Root}\dist\installer
OutputBaseFilename=ARES-Setup-{#AppVersion}
SetupIconFile={#Root}\desktop\assets\ares.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=ARES Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Root}\dist\ARES\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Optional: put MicrosoftEdgeWebView2RuntimeInstallerX64.exe (Microsoft's *offline* standalone installer) in
; desktop\redist\ before building, and Setup will install WebView2 on PCs that lack it - without internet.
#ifexist "redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
Source: "redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2
#define BundledWebView2
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "ARES Astronaut Health Command"
Name: "{group}\ARES data folder"; Filename: "{localappdata}\ARES\data"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
#ifdef BundledWebView2
Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Check: NeedsWebView2
#endif
Filename: "{app}\{#AppExe}"; Description: "Start ARES now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
const
  WV2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasVersion(Root: Integer; Key: String): Boolean;
var v: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', v) and (v <> '') and (v <> '0.0.0.0');
end;

function NeedsWebView2(): Boolean;
begin
  Result := not (HasVersion(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2) or
                 HasVersion(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2) or
                 HasVersion(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WV2));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
#ifndef BundledWebView2
  if NeedsWebView2() then
    Result := MsgBox('ARES displays its interface with the Microsoft Edge WebView2 Runtime, which was not found on ' +
      'this PC (it is part of Windows 11 and up-to-date Windows 10).' + #13#10#13#10 +
      'Install "Microsoft Edge WebView2 Runtime (Evergreen Standalone, x64)" first - it can be copied to this PC on a USB ' +
      'drive. Continue installing ARES anyway?', mbConfirmation, MB_YESNO) = IDYES;
#endif
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    data := ExpandConstant('{localappdata}\ARES');
    if DirExists(data) then
      if MsgBox('Also delete the ARES data on this PC (health records, emergency history, test results, backups, logs)?' +
                #13#10#13#10 + data + #13#10#13#10 + 'Choose No to keep it for a later reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(data, True, True, True);
  end;
end;
