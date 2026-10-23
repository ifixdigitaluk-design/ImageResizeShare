; Inno Setup script - creates ImageResizeShare-Setup.exe
; Build the app first (build.bat), then compile this file with Inno Setup 6.
#define AppName "Image Resize & Share"
#define AppVersion "3.1.1"
#define AppExe "ImageResizeShare.exe"

[Setup]
AppId={{6C3E2F7A-5B1D-4E8A-9F0C-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\Image Resize and Share
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=ImageResizeShare-Setup-{#AppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "openwith"; Description: "Add ""Edit with Image Resize & Share"" to the right-click menu for images"; GroupDescription: "Integration:"

[Files]
Source: "dist\ImageResizeShare\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\image\shell\ImageResizeShare"; ValueType: string; ValueData: "Edit with Image Resize && Share"; Tasks: openwith; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\image\shell\ImageResizeShare"; ValueName: "Icon"; ValueType: string; ValueData: """{app}\{#AppExe}"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\image\shell\ImageResizeShare\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
