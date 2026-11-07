from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


@pytest.fixture
def alembic_config() -> dict[str, str]:
    return {
        "file": str(Path(__file__).parents[2] / "alembic.ini"),
        "minimum_downgrade_revision": "0001",
    }


@pytest.fixture
def alembic_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'alembic.db'}")
    yield engine
    engine.dispose()
