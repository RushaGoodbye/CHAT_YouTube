#define MyAppName "RG YouTube Control"
#define MyAppVersion "0.2.6"
#define MyAppPublisher "RushaGoodbye"
#define MyAppExeName "RG YouTube Control.exe"

[Setup]
AppId={{A84C24D2-6A48-4F42-9B8C-6F1A8EBDBD2B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\RG YouTube Control
DefaultGroupName={#MyAppName}
OutputDir=..\installer
OutputBaseFilename=RG_YouTube_Control_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist\RG YouTube Control\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent