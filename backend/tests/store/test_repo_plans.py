from pathlib import Path

import pytest

from gleanery.store import open_database, repo_datasets, repo_plans
from tests.agent.test_plan_tools import body


async def test_versions_and_lock(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        plan = await repo_plans.create_draft(session, None, body(), 1)
        updated = await repo_plans.replace(session, plan.id, 1, body(2), 2)
        assert updated is not None and updated.version == 2
        with pytest.raises(repo_plans.VersionConflict) as conflict:
            await repo_plans.replace(session, plan.id, 1, body(), 3)
        assert conflict.value.current.version == 2
        dataset = await repo_datasets.create_dataset(session, "测试", "", None, 4)
        await repo_plans.confirm(session, updated, dataset.id, 4)
        with pytest.raises(repo_plans.PlanLocked):
            await repo_plans.replace(session, plan.id, 2, body(), 5)
    await db.close()
