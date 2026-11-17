import os
import tempfile

from englishnotes.storage.paths import data_directory


def configure_runtime() -> None:
    """Keep temporary files in the standard per-user application directory."""
    directory = data_directory() / "temp"
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(directory)
    os.environ["TMP"] = str(directory)
    tempfile.tempdir = str(directory)
