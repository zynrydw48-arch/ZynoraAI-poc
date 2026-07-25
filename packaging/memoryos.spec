# PyInstaller spec for NYXUS AI (formerly MemoryOS; Sprint 6: prove the app
# freezes and runs standalone, fully offline). Build with:
#   .venv\Scripts\pyinstaller packaging\memoryos.spec --noconfirm
#
# Produces dist\NyxusAI\ (onedir, not onefile) -- onefile would re-extract
# this multi-GB app on every launch, which is slow and pointless for a
# desktop app that isn't distributed as a single email attachment.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).resolve().parent

TESSERACT_INSTALL_DIR = r"C:\Program Files\Tesseract-OCR"

datas = []
binaries = []
hiddenimports = []

# These five have real, documented PyInstaller friction (lazy/plugin-style
# imports Analysis's static scan won't find on its own) -- collect_all pulls
# in everything each package might need rather than guessing hidden imports
# one ModuleNotFoundError at a time.
for pkg in ("torch", "torchvision", "transformers", "sentence_transformers", "PySide6"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

datas += [
    (str(PROJECT_ROOT / "tessdata"), "tessdata"),
    (TESSERACT_INSTALL_DIR, "Tesseract-OCR"),
    (str(PROJECT_ROOT / "packaging" / "model_cache"), "model_cache"),
    # Sprint 7: memoryos/ui/icons.py and memoryos/ui/styles/__init__.py both
    # resolve these at runtime via app_paths.get_resource_dir(), which is
    # sys._MEIPASS when frozen -- must land at the same relative path there.
    (str(PROJECT_ROOT / "memoryos" / "ui" / "icons"), "memoryos/ui/icons"),
    (str(PROJECT_ROOT / "memoryos" / "ui" / "styles" / "light.qss"), "memoryos/ui/styles"),
    (str(PROJECT_ROOT / "memoryos" / "ui" / "styles" / "dark.qss"), "memoryos/ui/styles"),
]

a = Analysis(
    [str(PROJECT_ROOT / "memoryos" / "app_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NyxusAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Sprint 9: windowed (no console) for the release build -- the visible
    # console from Sprints 6-8 was deliberate for build-and-verify work.
    # memoryos/utils/crash_logging.py (wired in app_main.py) guards against
    # sys.stdout/stderr being None in this mode and logs uncaught exceptions
    # to %APPDATA%\MemoryOS\crash.log instead of them vanishing silently
    # (that data folder name is intentionally unchanged by the rebrand --
    # see memoryos/utils/app_paths.py).
    console=False,
    disable_windowed_traceback=False,
    icon=str(PROJECT_ROOT / "packaging" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="NyxusAI",
)
