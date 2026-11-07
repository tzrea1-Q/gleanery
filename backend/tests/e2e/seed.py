import asyncio
from pathlib import Path

from gleanery.clock import SystemClock
from gleanery.collect.settings import WARMUP_KEY, rate_limits_key
from gleanery.store import open_database
from gleanery.store.models import ModelConfig
from gleanery.store.repo_settings import set_setting


async def seed(data_dir: Path) -> None:
    await asyncio.to_thread(data_dir.mkdir, parents=True, exist_ok=True)
    db = await open_database(data_dir)
    try:
        async with db.sessionmaker() as session:
            now = SystemClock().now_ms()
            config = ModelConfig(
                kind="openai_compatible",
                name="E2E 模型",
                preset="custom",
                base_url="http://127.0.0.1",
                api_style="chat",
                status="ok",
                status_reason=None,
                available_models=["e2e-model"],
                model_labels=None,
                client_id=None,
                models_fetched_at=now,
                favorites=[{"name": "e2e-model", "tool_test": "ok", "tool_test_error": None}],
                created_at=now,
                updated_at=now,
            )
            backup = ModelConfig(
                kind="openai_compatible",
                name="备用配置",
                preset="custom",
                base_url="http://127.0.0.1",
                api_style="chat",
                status="ok",
                status_reason=None,
                available_models=["e2e-backup"],
                model_labels=None,
                client_id=None,
                models_fetched_at=now,
                favorites=[{"name": "e2e-backup", "tool_test": "ok", "tool_test_error": None}],
                created_at=now,
                updated_at=now,
            )
            session.add_all([config, backup])
            await session.flush()
            await set_setting(
                session, "current_model", {"config_id": config.id, "model": "e2e-model"}
            )
            # e2e 用回放的取数器，不碰真站点：限速与预热都关掉，免得测试真的等待。
            # 直接写设置，绕过界面上的调参下限。
            for platform in ("bili", "xhs"):
                await set_setting(
                    session,
                    rate_limits_key(platform),
                    {
                        "page_interval": [0, 0],
                        "comment_page_interval": [0, 0],
                        "long_rest": [0, 0],
                        "min_task_gap_minutes": 0,
                    },
                )
            await set_setting(session, WARMUP_KEY, False)
            await session.commit()
    finally:
        await db.close()
