; TerraMind - Inno Setup script
;
; Build:
;   set TERRAMIND_BUNDLE=C:\path\to\TerraMind-beta5-win32-x64
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\terramind.iss
;
; The bundle is the extracted portable build produced by packaging\build-portable.ps1.
; Keep it on a short path (e.g. C:\tm\b): the bundle contains files whose absolute
; path exceeds 260 characters when the source root is deep.

#define AppName "TerraMind"
#define AppVersion "0.1.0-beta.5"
#define AppPublisher "Shubh Om Yadav"
#define AppExe "TerraMind.exe"

#define BundleDir GetEnv("TERRAMIND_BUNDLE")
#if BundleDir == ""
  #error TERRAMIND_BUNDLE is not set. Point it at the extracted portable bundle.
#endif

[Setup]
AppId={{8F3C2B1A-7D4E-4A9B-9C2E-5B6A1F0D3E7C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion=0.1.0.5
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=TerraMind-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
AllowNoIcons=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
