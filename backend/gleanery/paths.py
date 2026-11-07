import os
from pathlib import Path

from platformdirs import user_data_dir


def data_directory() -> Path:
    path = Path(os.environ.get("GLEANERY_DATA_DIR") or user_data_dir("gleanery", appauthor=False))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path
