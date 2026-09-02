#define MyAppName "Finanz Cockpit"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Finanz Cockpit"
#define MyAppExeName "FinanzCockpit.exe"

[Setup]
AppId={{8E39F6D6-A0D9-4BA5-85B4-3A84F7A2C64C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\FinanzCockpit
DefaultGroupName=Finanz Cockpit
DisableProgramGroupPage=yes
OutputDir=..\..\dist\windows
OutputBaseFilename=finanz-cockpit-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\icons\finanz-cockpit.ico

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "..\..\dist\FinanzCockpit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Finanz Cockpit"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"
Name: "{autodesktop}\Finanz Cockpit"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"; Description: "Finanz Cockpit starten"; Flags: nowait postinstall skipifsilent
