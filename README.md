# Nyxus-AI
[Download NyxusAI for Windows (EXE Installer)](https://mega.nz/file/jDQihIKQ#iSUErrzK15oa_dqxh1DiEigkQw8sEYURm-89TCi1u7E)
Semantic search over local files by natural-language description, not filename.

v1.0.0 — the V1 desktop app is feature-complete: a redesigned UI, background
indexing that's parallel and fast (~2.85x speedup over a naive sequential
pass — see `PERFORMANCE_BASELINE.md`), local search history, file actions,
light/dark/system theming, and a Windows installer. The original PoC's CLI is
kept working as a verified fallback until the SQLite-backed V1 path is fully
retired (still deferred, not yet scheduled).

## Install (recommended)

Download `packaging/installer_output/NyxusAI-Setup-1.0.0.exe` and run it —
no admin rights needed, installs to your own user profile
(`%LOCALAPPDATA%\Programs\MemoryOS`), with Start Menu and optional Desktop
shortcuts. Windows SmartScreen will show an "unknown publisher" warning on
first run (no code-signing certificate yet) — choose "More info" → "Run
anyway" if you trust the source you got it from.

Uninstalling (via Add/Remove Programs, or the Start Menu shortcut) always
leaves your search index and history in place unless you explicitly check
the "also delete my data" box the uninstaller offers.

## Run from source

### Prerequisites

- Python 3.12
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed system-wide (`winget install tesseract-ocr.tesseract`)
- English + Hebrew tessdata in `./tessdata/` (`eng.traineddata`, `heb.traineddata` — not bundled with the Windows Tesseract installer by default)

### Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### Run: desktop app

```
.venv\Scripts\python -m memoryos.app_main
```

Pick a folder, click Start Indexing, then search — indexing runs in the
background across multiple threads (its own connections + a bounded worker
pool), so the window and search stay responsive throughout. Pause/Resume/
Cancel buttons are available while indexing runs, and it will automatically
pause itself (showing why) if CPU usage from *other* applications is high,
RAM usage is high, Battery Saver is on, battery is low, or a fullscreen
app/game/presentation is active — resuming automatically once conditions
clear. Recent searches appear in the "Recent searches" panel — double-click
one to re-run it, or use Clear to wipe it (local-only, never transmitted).
Every result card has inline Open/Reveal in Folder/Copy Path/Rename/Delete
actions (also available via right-click) — Delete moves to the Recycle Bin,
never a permanent delete, and the index updates immediately. The Settings >
Theme menu switches between Light, Dark, and System (follows the OS theme
live); Help > About MemoryOS shows the current version. Data lives in
`.memoryos/memoryos.sqlite3` when run from source (`%APPDATA%\MemoryOS\` when
installed/frozen).

### Run: CLI (PoC fallback)

```
.venv\Scripts\python -m memoryos.cli.main
```

Scans and indexes the project directory recursively (supported types: jpg/jpeg/png/bmp/webp, pdf, pptx, docx, xlsx), then prompts for natural-language descriptions and shows the top 10 matches with similarity scores and match reasons. Re-runs only re-process files that changed since the last index (cached in `.index/`, independent of the desktop app's `.memoryos/` database).

### Tests

```
.venv\Scripts\python -m pytest tests/
```

## Building the frozen app + installer

Produces an offline-capable folder (`dist/MemoryOS/`, ~4.5GB — bundles the
Python runtime, Tesseract, and all model weights so nothing needs to be
installed or downloaded separately, including on first run) and then wraps
it in a Windows installer:

```
.venv\Scripts\python packaging\prepare_offline_cache.py
.venv\Scripts\pyinstaller packaging\memoryos.spec --noconfirm
"<path to Inno Setup 6>\ISCC.exe" packaging\memoryos.iss
```

The frozen `dist/MemoryOS/MemoryOS.exe` runs standalone (verified by copying
it to a machine/location with no Python, no venv, and no system Tesseract
install) and windowed (no console — uncaught errors are logged to
`%APPDATA%\MemoryOS\crash.log` instead of a visible console). Its database
lives in `%APPDATA%\MemoryOS\memoryos.sqlite3`, separate from both the dev
app's `.memoryos/` and the CLI's `.index/`. See `RELEASE_CHECKLIST.md` before
cutting a new release, and keep `memoryos/__version__.py` and
`packaging/memoryos.iss`'s `MyAppVersion` in sync on every version bump.

There's no code-signing certificate yet, so both the installer and the
frozen exe show an "unknown publisher" SmartScreen warning — a known,
disclosed limitation, not a defect.
