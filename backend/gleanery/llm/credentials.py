import json
import os
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

from gleanery.deps import CredentialBackend


class KeyringCredentialStore:
    backend: CredentialBackend = "keyring"

    def get(self, config_id: int) -> str | None:
        return keyring.get_password("gleanery", f"model-config:{config_id}")

    def set(self, config_id: int, secret: str) -> None:
        keyring.set_password("gleanery", f"model-config:{config_id}", secret)

    def delete(self, config_id: int) -> None:
        with suppress(PasswordDeleteError):
            keyring.delete_password("gleanery", f"model-config:{config_id}")


class FileCredentialStore:
    backend: CredentialBackend = "file"

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "credentials.json"

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def get(self, config_id: int) -> str | None:
        return self._read().get(str(config_id))

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".credentials-")
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(data, file)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set(self, config_id: int, secret: str) -> None:
        data = self._read()
        data[str(config_id)] = secret
        self._write(data)

    def delete(self, config_id: int) -> None:
        data = self._read()
        if data.pop(str(config_id), None) is not None:
            self._write(data)


def open_credential_store(data_dir: Path) -> KeyringCredentialStore | FileCredentialStore:
    username = f"probe:{uuid.uuid4()}"
    value = str(uuid.uuid4())
    try:
        keyring.set_password("gleanery", username, value)
        try:
            if keyring.get_password("gleanery", username) != value:
                raise RuntimeError("钥匙串读取失败")
        finally:
            keyring.delete_password("gleanery", username)
        return KeyringCredentialStore()
    except Exception:
        return FileCredentialStore(data_dir)
