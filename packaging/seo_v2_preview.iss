#define MyAppName "RG SEO v2 Preview"
#define MyAppVersion "0.1.1"
#define MyAppExeName "RG SEO v2 Preview.exe"

[Setup]
AppId={{C6AB06B1-C9BC-4613-86A3-973D8D10B5BA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=RushaGoodbye
DefaultDirName={autopf}\RG SEO v2 Preview
DefaultGroupName={#MyAppName}
OutputDir=..\seo_v2_installer
OutputBaseFilename=RG_SEO_V2_Preview_Setup_0_1_1
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=no
RestartApplications=no
PrivilegesRequired=lowest

[Files]
Source: "..\dist\RG SEO v2 Preview\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Відкрити {#MyAppName}"; Flags: nowait postinstall skipifsilent
