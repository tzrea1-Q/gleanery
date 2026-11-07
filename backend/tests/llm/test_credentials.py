from pathlib import Path

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from gleanery.llm.credentials import (
    FileCredentialStore,
    KeyringCredentialStore,
    open_credential_store,
)


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[service, username] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.values.pop((service, username), None) is None:
            raise PasswordDeleteError()


def test_stores(tmp_path: Path) -> None:
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    try:
        store = open_credential_store(tmp_path)
        assert isinstance(store, KeyringCredentialStore)
        store.set(1, "key")
        assert memory.values == {("gleanery", "model-config:1"): "key"}
        assert store.get(1) == "key"
        store.delete(1)
        assert store.get(1) is None
    finally:
        keyring.set_keyring(previous)
    file_store = FileCredentialStore(tmp_path)
    file_store.set(1, "key")
    assert file_store.get(1) == "key"
    assert file_store.path.stat().st_mode & 0o777 == 0o600
    file_store.delete(1)
    assert file_store.get(1) is None


def test_openai_responses_model(tmp_path: Path) -> None:
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from gleanery.llm.client import make_http_client, make_model
    from gleanery.store.models import ModelConfig

    config = ModelConfig(
        preset="openai", base_url="https://api.openai.com/v1", api_style="responses"
    )
    model = make_model(config, "model", "key", make_http_client(None))
    assert isinstance(model, OpenAIResponsesModel)
