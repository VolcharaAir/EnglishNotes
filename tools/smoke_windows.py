"""Run the actual frozen EXE twice, including after relocation, on Windows.

This is a launch/storage smoke check; source UI tests cover interactive editing.
No credentials, live user database, or installed Python are supplied to the EXE.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from englishnotes.application.service import NotesService
from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository


def run_and_close(executable: Path, env: dict[str, str], cwd: Path) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process = subprocess.Popen([str(executable)], env=env, cwd=cwd)
    found = []

    @callback_type
    def visit(handle, extra):
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(handle, title, len(title))
        if not title.value.startswith("EnglishNotes"):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        opened = kernel32.OpenProcess(0x1000, False, pid.value)
        if opened:
            try:
                image = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(image))
                if kernel32.QueryFullProcessImageNameW(opened, 0, image, ctypes.byref(length)):
                    if Path(image.value).resolve() == executable.resolve():
                        found.append(handle)
            finally:
                kernel32.CloseHandle(opened)
        return True

    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            user32.EnumWindows(visit, 0)
            if found:
                break
            if process.poll() is not None:
                raise RuntimeError(f"EXE exited before opening its window: {process.returncode}")
            time.sleep(0.2)
        if not found:
            raise RuntimeError("Frozen application window did not appear")
        if not user32.PostMessageW(found[0], 0x0010, 0, 0):  # WM_CLOSE -> Qt closeEvent
            raise ctypes.WinError(ctypes.get_last_error())
        if process.wait(timeout=30) != 0:
            raise RuntimeError(f"Frozen application failed: {process.returncode}")
    finally:
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            process.wait(timeout=15)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This smoke check requires real Windows")
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="EnglishNotes-smoke-") as folder:
        root = Path(folder)
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(root / "profile")
        env["QT_QPA_PLATFORM"] = "windows"
        env["ENGLISHNOTES_DISABLE_CLOUD"] = "1"
        env.pop("ENGLISHNOTES_DATA_DIR", None)
        # The EXE must use its bundled interpreter and Qt plugins.
        for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            env.pop(key, None)
        run_and_close(executable, env, root)
        path = root / "profile" / "EnglishNotes" / "englishnotes.sqlite3"
        assert path.is_file(), "First run did not create the database in LocalAppData"
        database = Database(path)
        try:
            service = NotesService(SQLiteNotesRepository(database))
            lesson = service.create_lesson()
            note = service.save_note(service.create_note(lesson.id), "Smoke", "Keep me — ✅")
        finally:
            database.close()
        relocated = root / "moved app" / "EnglishNotes moved.exe"
        relocated.parent.mkdir()
        shutil.copy2(executable, relocated)
        run_and_close(relocated, env, relocated.parent)
        database = Database(path)
        try:
            assert SQLiteNotesRepository(database).list_notes(lesson.id) == [note]
            assert database.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            database.close()
        assert not (relocated.parent / "englishnotes.sqlite3").exists()
        assert not (path.parent / "englishnotes.lock").exists()
    print("Windows EXE smoke passed: launch, graceful close, database reuse, relocation.")


if __name__ == "__main__":
    main()
