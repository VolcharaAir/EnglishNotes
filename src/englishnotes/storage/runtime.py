import os
import sys
import tempfile

from englishnotes.storage.paths import data_directory


def configure_runtime() -> None:
    """Keep application-controlled temporary files on D: on Windows."""
    if sys.platform != "win32":
        return
    directory = data_directory() / "temp"
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(directory)
    os.environ["TMP"] = str(directory)
    tempfile.tempdir = str(directory)
