"""共用的内容库造数。

两个数据集：`a` 有内容 v1、v2、v3，`b` 有 v3、v4；v3 两个数据集共享。
平台文本里都嵌了哨兵字符串 `SENTINEL`，用来断言它们只出现在 `untrusted` 里。
时间按 Asia/Shanghai：v1 发布于 2026-10-01 10:00，v2 于 10-02，v3 于 10-03，v4 发布时间缺失。
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.platforms.types import (
    AuthorRecord,
    CommentRecord,
    ContentRecord,
    Counts,
    SubtitleRecord,
    SubtitleSegment,
)
from gleanery.store import repo_content, repo_datasets
from gleanery.store.models import Comment

TZ = ZoneInfo("Asia/Shanghai")
SENTINEL = "哨兵ZQX"
NOW = int(datetime(2026, 10, 20, 12, 0, tzinfo=TZ).timestamp() * 1000)


def at(day: int, hour: int = 10) -> int:
    return int(datetime(2026, 10, day, hour, 0, tzinfo=TZ).timestamp() * 1000)


@dataclass
class Library:
    dataset_a: int
    dataset_b: int
    contents: dict[str, int]
    """平台内 ID（v1…v4）→ 内部 ID。"""
    comments: dict[str, int]
    """平台内 ID（c1…）→ 内部 ID。c1、c2 是 v1 的一级评论，r1、r2 是 c1 的回复，c3 属于 v3，c4 属于 v4。"""


def _author(name: str) -> AuthorRecord:
    return AuthorRecord(platform="bili", platform_id=f"u-{name}", nickname=f"{name}{SENTINEL}")


def _content(
    pid: str, title: str, body: str, published_at: int | None, likes: int | None, plays: int | None
) -> ContentRecord:
    return ContentRecord(
        platform="bili",
        platform_id=pid,
        url=f"https://www.bilibili.com/video/{pid}",
        kind="video",
        title=f"{title}{SENTINEL}",
        body=f"{body}{SENTINEL}",
        author=_author(f"作者{pid}"),
        published_at=published_at,
        counts=Counts(likes=likes, favorites=1, comments=10, shares=0, plays=plays),
        tags=[f"标签{SENTINEL}"],
        completeness="detail" if pid != "v2" else "summary",
        ext={
            "coins": 5,
            "danmaku": 7,
            "duration": 61,
            "tname": "数码",
            "counts_approx": pid == "v1",
        },
    )


def _comment(
    pid: str, content: str, body: str, likes: int, root: str | None = None, published: int = 0
) -> CommentRecord:
    return CommentRecord(
        platform="bili",
        platform_id=pid,
        content_platform_id=content,
        root_platform_id=root,
        parent_platform_id=root,
        author=_author(f"评论者{pid}"),
        body=f"{body}{SENTINEL}",
        published_at=published or at(5),
        likes=likes,
        reply_count=2 if pid == "c1" else 0,
        ip_location=f"上海{SENTINEL}",
    )


async def seed_library(session: AsyncSession) -> Library:
    """建两个数据集并提交。"""
    records = [
        _content("v1", "耳机测评", "音质不错但是续航太差", at(1), 1000, 50000),
        _content("v2", "耳机开箱", "做工一般", at(2), 200, 8000),
        _content("v3", "降噪对比", "降噪很强，佩戴有点夹头", at(3), 500, None),
        _content("v4", "无发布时间", "=1+1 公式样的正文", None, None, 100),
    ]
    contents = await repo_content.upsert_contents(session, records, None, NOW)
    await repo_content.upsert_comments(
        session,
        contents["v1"],
        [
            _comment("c1", "v1", "续航太差了，一天三充", 90, published=at(6)),
            _comment("c2", "v1", "音质可以", 10, published=at(7)),
            _comment("r1", "v1", "同感，续航真差", 5, root="c1", published=at(8)),
            _comment("r2", "v1", "我的还好", 1, root="c1", published=at(9)),
        ],
        None,
        NOW,
    )
    await repo_content.upsert_comments(
        session, contents["v3"], [_comment("c3", "v3", "夹头，戴久了疼", 30)], None, NOW
    )
    await repo_content.upsert_comments(
        session, contents["v4"], [_comment("c4", "v4", "@某人 看看", 2)], None, NOW
    )
    await repo_content.upsert_subtitles(
        session,
        contents["v1"],
        [
            SubtitleRecord(
                content_platform_id="v1",
                part_id="cid1",
                part_title=f"P1{SENTINEL}",
                lang="ai-zh",
                ai_generated=True,
                segments=[
                    SubtitleSegment.model_validate(
                        {"from": 0, "to": 1, "content": f"大家好{SENTINEL}"}
                    ),
                    SubtitleSegment.model_validate({"from": 1, "to": 2, "content": "今天测耳机"}),
                ],
            )
        ],
        NOW,
    )
    dataset_a = await repo_datasets.create_dataset(session, "耳机", "耳机评价", None, NOW)
    dataset_b = await repo_datasets.create_dataset(session, "降噪", "", None, NOW)
    await repo_datasets.add_to_dataset(
        session, dataset_a.id, [contents[p] for p in ("v1", "v2", "v3")], None, NOW
    )
    await repo_datasets.add_to_dataset(
        session, dataset_b.id, [contents[p] for p in ("v3", "v4")], None, NOW + 1
    )
    comments = {row.platform_id: row.id for row in await session.scalars(select(Comment))}
    await session.commit()
    return Library(dataset_a.id, dataset_b.id, contents, comments)
