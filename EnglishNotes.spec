# Build on Windows: python -m PyInstaller --clean --noconfirm EnglishNotes.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
config = root / "work" / "bundle" / "cloud.json"
if not config.is_file():
    raise SystemExit("Run tools/prepare_cloud_config.py first (or use --local).")
backend = "Windows" if sys.platform == "win32" else ("macOS" if sys.platform == "darwin" else "SecretService")
analysis = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(config), "englishnotes/resources")],
    hiddenimports=["keyring.backends." + backend] + (collect_submodules("win32ctypes") if sys.platform == "win32" else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtPdf", "PySide6.QtQml", "PySide6.QtQuick",
        "pytest", "ruff",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="EnglishNotes", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    runtime_tmpdir=None,
)
