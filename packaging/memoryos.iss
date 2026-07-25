; NYXUS AI installer (formerly MemoryOS; Sprint 8). Wraps the existing frozen
; PyInstaller build (dist\NyxusAI\, see memoryos.spec) in a per-user installer
; -- no admin/UAC prompt required, matching how many modern desktop apps
; (VS Code's user installer, Discord) ship without a code-signing
; certificate. Compile with:
;   "C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" packaging\memoryos.iss

#define MyAppName "NYXUS AI"
; Sprint 9: keep in sync by hand with memoryos/__version__.py's __version__ --
; Inno's preprocessor can't import a Python constant, so these are two
; separately-hardcoded values, not a shared build-time source of truth.
#define MyAppVersion "1.1.0"
#define MyAppPublisher "NYXUS AI"
#define MyAppExeName "NyxusAI.exe"

[Setup]
; This GUID must stay constant across every future version (including this
; rebrand) so Setup detects upgrades correctly -- it identifies the same
; underlying product across name changes, never regenerate it for a routine
; version bump or a rename.
AppId={{2B720FD5-B1CC-462F-80FF-B4B8A5EB8528}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install (no admin/UAC prompt) -- {userpf} is the per-user
; equivalent of Program Files, e.g. %LOCALAPPDATA%\Programs\NYXUS AI.
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=installer_output
OutputBaseFilename=NyxusAI-Setup-{#MyAppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; The payload is ~4.5GB of mostly-already-compressed ML binaries -- "normal"
; is a reasonable size/compile-time tradeoff; switch to lzma2/fast locally
; if iterating on this script gets too slow.
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\NyxusAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ShouldDeleteUserData: Boolean;

// NYXUS AI keeps its SQLite index/settings/search-history in
// %APPDATA%\MemoryOS (see memoryos/utils/app_paths.py's get_user_data_dir(),
// which resolves to exactly this path when frozen -- intentionally left as
// "MemoryOS" internally by the rebrand, since renaming it would relocate
// every existing user's data with no migration step) -- entirely outside the
// install directory Setup manages, so it survives a plain uninstall by
// default. This asks an explicit, opt-in question before ever deleting it.
//
// NOTE: an earlier version of this used a custom TSetupForm (via
// TSetupForm.Create) with a real checkbox control, but that raised a
// runtime "Resource TSetupForm not found" error when actually run as the
// uninstaller -- TSetupForm depends on a compiled VCL form resource that
// Inno Setup's separate uninstaller executable (unins000.exe) does not
// carry, unlike the main installer (Setup.exe). MsgBox is a thin wrapper
// around the Win32 MessageBox API with no such dependency, so it works
// correctly in both contexts -- confirmed by testing this exact uninstaller.
function InitializeUninstall(): Boolean;
var
  Response: Integer;
begin
  Result := True;
  ShouldDeleteUserData := False;

  // Scripted/silent uninstalls (Windows' own "Apps & Features" bulk
  // uninstall, or an automated verification run) must never block on a
  // modal dialog with nobody there to answer it -- skip straight through,
  // leaving user data untouched.
  if UninstallSilent() then
    Exit;

  Response := MsgBox(
    'Also permanently delete your NYXUS AI search history and file index database?' + #13#10 + #13#10 +
    'WARNING: this cannot be undone. If you plan to reinstall NYXUS AI later, or are ' +
    'just upgrading to a new version, choose No to keep your existing search index ' +
    'and history.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2
  );
  // MB_DEFBUTTON2 makes "No" the default -- an accidental Enter-press must
  // never delete data.
  ShouldDeleteUserData := (Response = IDYES);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  Attempt: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if ShouldDeleteUserData then
    begin
      DataDir := ExpandConstant('{userappdata}\MemoryOS');
      // A file here (e.g. the SQLite database) can occasionally still be
      // transiently locked -- antivirus or the search indexer scanning it
      // right after neighboring files were just deleted -- confirmed by
      // testing this exact uninstall path. A few short retries clears this
      // without ever bothering the user about it.
      Attempt := 0;
      while DirExists(DataDir) and (Attempt < 5) do
      begin
        DelTree(DataDir, True, True, True);
        if DirExists(DataDir) then
        begin
          Sleep(500);
          Attempt := Attempt + 1;
        end;
      end;
    end;
  end;
end;
