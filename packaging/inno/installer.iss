; ClearMic — Inno Setup 6 Windows Installer & Optional Uninstaller Script (v1.0.0)
; Packages PyInstaller --onedir output (dist\ClearMic\*) into a clean Windows x64 installer.
;
; Build commands:
;   python scripts/build_exe.py --skip-zip
;   iscc /DMyAppVersion=1.0.0 packaging\inno\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#if Pos("-", MyAppVersion) > 0
  #define MyAppNumericVersion Copy(MyAppVersion, 1, Pos("-", MyAppVersion) - 1)
#else
  #define MyAppNumericVersion MyAppVersion
#endif

#define MyAppName "ClearMic"
#define MyAppPublisher "Andac Basaran"
#define MyAppURL "https://clearmic.andacbasaran.com"
#define MyAppRepo "https://github.com/Andacbasaran/ClearMic"
#define MyAppExeName "ClearMic.exe"

[Setup]
AppId={{9B6D12E5-41F3-4A89-9E71-3F5A2B4C8D10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppRepo}/issues
AppUpdatesURL={#MyAppRepo}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=ClearMic-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=yes
VersionInfoVersion={#MyAppNumericVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} - Offline AI Microphone Noise Suppressor & Voice Studio
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\ClearMic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    AppDataDir := ExpandConstant('{userappdata}\ClearMic');
    if not UninstallSilent and DirExists(AppDataDir) then
    begin
      if MsgBox(
        'Do you also want to remove your ClearMic settings, custom presets, and downloaded GTCRN ONNX model (' + AppDataDir + ')?',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        DelTree(AppDataDir, True, True, True);
      end;
    end;
  end;
end;
