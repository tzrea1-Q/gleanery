from pathlib import Path

import pytest

from gleanery.collect.plan import PlanBody
from gleanery.collect.plan_check import check
from gleanery.platforms.types import ContentRecord
from gleanery.store import open_database, repo_content
from tests.agent.test_plan_tools import FakeCollect

NOTE = "abcdef0123456789abcdef01"
OTHER = "abcdef0123456789abcdef02"
TOKEN = "secret-token"


@pytest.mark.parametrize("target", [f"https://xiaohongshu.com/explore/{NOTE}", NOTE])
async def test_library_fills_link(tmp_path: Path, target: str) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            await repo_content.upsert_contents(
                session,
                [
                    ContentRecord(
                        platform="xhs",
                        platform_id=NOTE,
                        url="https://xiaohongshu.com",
                        kind="image_text",
                        completeness="summary",
                        ext={"xsec_token": TOKEN, "xsec_source": "library"},
                    )
                ],
                None,
                1,
            )
            plan = PlanBody.model_validate(
                {
                    "title": "测试",
                    "sections": [
                        {"platform": "xhs", "depth": {}, "quantity": 0, "targets": [target]}
                    ],
                }
            )
            issues, resolved = await check(session, plan, FakeCollect(), 1)
            assert not [issue for issue in issues if issue.code == "UNRESOLVABLE_LINK"]
            assert resolved["xhs"][0].ext == {"xsec_token": TOKEN, "xsec_source": "library"}
    finally:
        await db.close()


async def test_targets_and_redaction(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            ids = await repo_content.upsert_contents(
                session,
                [
                    ContentRecord(
                        platform="xhs",
                        platform_id=NOTE,
                        url="https://xiaohongshu.com",
                        kind="image_text",
                        completeness="summary",
                        ext={"xsec_token": TOKEN, "xsec_source": "library", "other": "ignored"},
                    ),
                    ContentRecord(
                        platform="bili",
                        platform_id="BV1234567890",
                        url="https://www.bilibili.com/video/BV1234567890",
                        kind="video",
                        completeness="summary",
                    ),
                ],
                None,
                1,
            )
            plan = PlanBody.model_validate(
                {
                    "title": "测试",
                    "sections": [
                        {
                            "platform": "xhs",
                            "depth": {},
                            "quantity": 0,
                            "targets": [
                                f"https://xiaohongshu.com/explore/{OTHER}?xsec_token=link-token&xsec_source=app",
                                f"content:{ids[NOTE]}",
                                OTHER,
                                f"content:{ids['BV1234567890']}",
                                "https://evil.test/path?xsec_token=private#fragment",
                            ],
                        },
                        {
                            "platform": "bili",
                            "depth": {},
                            "quantity": 0,
                            "targets": ["BV1234567890"],
                        },
                    ],
                }
            )
            issues, resolved = await check(session, plan, FakeCollect(), 1)
            assert [ref.ext for ref in resolved["xhs"]] == [
                {"xsec_token": "link-token", "xsec_source": "app"},
                {"xsec_token": TOKEN, "xsec_source": "library"},
            ]
            assert resolved["bili"][0].platform_id == "BV1234567890"
            errors = [issue.message for issue in issues if issue.code == "UNRESOLVABLE_LINK"]
            assert len(errors) == 3
            assert f"{OTHER} 缺少 xsec_token：请从小红书网页或 App 复制完整的分享链接" in errors
            assert all(
                "private" not in error and "?" not in error and "#" not in error for error in errors
            )
    finally:
        await db.close()
