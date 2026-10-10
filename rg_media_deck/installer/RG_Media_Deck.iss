#define MyAppName "RG Media Deck"
#define MyAppVersion "0.3.1"
#define MyAppExeName "RG_Media_Deck.exe"
[Setup]
AppId={{C69CBCC4-3124-4124-804D-75D0B97D0224}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=RushaGoodbye
DefaultDirName={localappdata}\Programs\RG Media Deck
DefaultGroupName=RG Media Deck
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist_installer
OutputBaseFilename=RG_Media_Deck_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Files]
Source: "..\dist\RG_Media_Deck\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RG Media Deck"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\RG Media Deck"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Створити значок на робочому столі"; GroupDescription: "Додаткові параметри:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустити RG Media Deck"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: ShouldStartWhenSilent

[Code]
function ShouldStartWhenSilent(): Boolean;
begin
  Result := WizardSilent;
end;
