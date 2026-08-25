; TEMM Inno Setup Installer Script
; Target: modern 64-bit Windows (Windows 10+)
; Requires: Inno Setup 6.x (iscc.exe)
; Build: iscc.exe /Qp tools\installer\temm-setup.iss

#define AppName "TEMM"
#define AppVersion "0.1.0"
#define AppPublisher "TEMM Contributors"
#define AppURL "https://github.com/niceteem/temm"
#define AppExeName "TEMM.cmd"

[Setup]
AppId={{B7E3F4A1-2C8D-4E9F-A1B2-3C4D5E6F7A8B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\TEMM
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=TEMM-Setup-{#AppVersion}-x64
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Runtime package contents (built by tools/installer/build-windows-package.ps1)
Source: "..\..\dist\runtime\*"; DestDir: "{app}\versions\{#AppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

; License
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dependency-licenses.json"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\TEMM Data"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch TEMM"; Flags: nowait postinstall skipifsilent shellexec

[INI]
Filename: "{app}\install-state.json"; Section: ""; Key: ""; String: "{{"schema_version"":""1.0"",""current_version"":""{#AppVersion}"",""data_root"":""{localappdata}\\TEMM Data""}}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  LauncherPath: String;
  LauncherContent: String;
begin
  if CurStep = ssPostInstall then
  begin
    LauncherPath := ExpandConstant('{app}\TEMM.cmd');
    LauncherContent :=
      '@echo off' + #13#10 +
      'set "AI_FLEET_DATA_DIR=' + ExpandConstant('{localappdata}\TEMM Data') + '"' + #13#10 +
      'pushd "%~dp0versions\{#AppVersion}"' + #13#10 +
      'call "start.bat" %*' + #13#10 +
      'set "AI_FLEET_EXIT=%ERRORLEVEL%"' + #13#10 +
      'popd' + #13#10 +
      'exit /b %AI_FLEET_EXIT%' + #13#10;
    SaveStringToFile(LauncherPath, LauncherContent, False);
  end;
end;

[UninstallDelete]
Type: files; Name: "{app}\TEMM.cmd"
Type: files; Name: "{app}\install-state.json"
Type: dirifempty; Name: "{app}\versions\{#AppVersion}"
Type: dirifempty; Name: "{app}\versions"
Type: dirifempty; Name: "{app}"
; Data directory is preserved by default; user must manually delete if desired
