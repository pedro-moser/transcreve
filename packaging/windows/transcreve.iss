#ifndef MyAppVersion
  #define MyAppVersion "2.1.0-beta.1"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\..\dist\Transcreve"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\release"
#endif

[Setup]
AppId={{8C6E9E43-A9C6-4A66-8E45-7F6C91F71FC1}
AppName=Transcreve
AppVersion={#MyAppVersion}
AppPublisher=Pedro Moser
AppPublisherURL=https://github.com/pedro-moser/transcreve
AppSupportURL=https://github.com/pedro-moser/transcreve/issues
AppUpdatesURL=https://github.com/pedro-moser/transcreve/releases
DefaultDirName={localappdata}\Programs\Transcreve
DefaultGroupName=Transcreve
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#MyOutputDir}
OutputBaseFilename=Transcreve-{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\..\assets\transcreve-icon.ico
UninstallDisplayIcon={app}\Transcreve.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Transcreve"; Filename: "{app}\Transcreve.exe"
Name: "{autodesktop}\Transcreve"; Filename: "{app}\Transcreve.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Transcreve.exe"; Description: "Abrir o Transcreve"; Flags: nowait postinstall skipifsilent
