; Instalador de Windows (Inno Setup 6). Compilar con:
;   iscc packaging\windows\installer.iss
; Requiere haber generado antes dist\NetworkMonitoring con PyInstaller.

#define AppName "Network Monitoring"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "NetworkMonitoring.exe"

[Setup]
AppId={{6E2B4C1A-8F3D-4B7E-9C21-5A0D3E9F1B42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MyNameIsMarkel
AppPublisherURL=https://github.com/MyNameIsMarkel/Network-Monitoring
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=NetworkMonitoring-Setup-{#AppVersion}
SetupIconFile=..\..\netmon\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assocdrawio"; Description: "Abrir los ficheros .drawio con {#AppName}"; GroupDescription: "Asociaciones:"; Flags: unchecked

[Files]
Source: "..\..\dist\NetworkMonitoring\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.drawio\OpenWithProgids"; ValueType: string; ValueName: "NetworkMonitoring.drawio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocdrawio
Root: HKA; Subkey: "Software\Classes\NetworkMonitoring.drawio"; ValueType: string; ValueName: ""; ValueData: "Diagrama draw.io"; Flags: uninsdeletekey; Tasks: assocdrawio
Root: HKA; Subkey: "Software\Classes\NetworkMonitoring.drawio\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assocdrawio
Root: HKA; Subkey: "Software\Classes\NetworkMonitoring.drawio\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assocdrawio

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
