from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.deps import CredentialBackend, ResolvedModel


class MemoryCredentialStore:
    """测试用的内存凭证存储。"""

    backend: CredentialBackend = "memory"

    def __init__(self) -> None:
        self._secrets: dict[int, str] = {}

    def get(self, config_id: int) -> str | None:
        return self._secrets.get(config_id)

    def set(self, config_id: int, secret: str) -> None:
        self._secrets[config_id] = secret

    def delete(self, config_id: int) -> None:
        self._secrets.pop(config_id, None)


async def no_model(session: AsyncSession) -> ResolvedModel | None:
    return None
