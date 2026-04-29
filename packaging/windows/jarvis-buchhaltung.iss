#define MyAppName "Jarvis Buchhaltung"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "JARVIS-ai-code"
#define MyAppExeName "JarvisBuchhaltung.exe"

[Setup]
AppId={{8E39F6D6-A0D9-4BA5-85B4-3A84F7A2C64C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\JarvisBuchhaltung
DefaultGroupName=Jarvis Buchhaltung
DisableProgramGroupPage=yes
OutputDir=..\..\dist\windows
OutputBaseFilename=jarvis-buchhaltung-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "..\..\dist\JarvisBuchhaltung\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Jarvis Buchhaltung"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Jarvis Buchhaltung"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Jarvis Buchhaltung starten"; Flags: nowait postinstall skipifsilent
