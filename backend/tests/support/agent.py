from pathlib import Path
from typing import Any

from gleanery.agent.deps import AgentDeps
from gleanery.events import EventBus
from gleanery.query.sql import ReadOnlySql
from gleanery.store.db import DB_FILENAME, Database
from tests.support.library import TZ


def agent_deps(
    db: Database,
    data_dir: Path,
    *,
    collect: Any,
    clock: Any,
    events: EventBus | None = None,
    conversation_id: int = 1,
) -> AgentDeps:
    """测试用的 `AgentDeps`；时区固定为 Asia/Shanghai，`run_sql` 读 `data_dir` 里的库。"""
    return AgentDeps(
        db.sessionmaker,
        conversation_id,
        clock,
        events or EventBus(),
        collect,
        ReadOnlySql(data_dir / DB_FILENAME),
        TZ,
        data_dir,
    )
