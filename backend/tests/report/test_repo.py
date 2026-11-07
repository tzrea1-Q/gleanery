from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from gleanery.report import repo
from gleanery.report.citations import CitationRef
from gleanery.store import cleanup, open_database, repo_datasets
from gleanery.store.models import Content, Conversation, Report, ReportCitation, ReportRevision
from tests.support.library import NOW, seed_library


def test_edits() -> None:
    assert (
        repo.apply_edits(
            "abc", [{"old_text": "ab", "new_text": "x"}, {"old_text": "xc", "new_text": "z"}]
        )
        == "z"
    )
    with pytest.raises(repo.EditNotFound) as missing:
        repo.apply_edits("abc", [{"old_text": "", "new_text": "x"}])
    assert missing.value.index == 0
    with pytest.raises(repo.EditAmbiguous) as ambiguous:
        repo.apply_edits("aaa", [{"old_text": "a", "new_text": "x"}])
    assert ambiguous.value.count == 3
    with pytest.raises(repo.EditAmbiguous) as overlapping:
        repo.apply_edits("aaa", [{"old_text": "aa", "new_text": "x"}])
    assert overlapping.value.count == 2


async def test_reports(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
            conversation = Conversation(title="对话", created_at=NOW, updated_at=NOW)
            session.add(conversation)
            await session.flush()
            content_id = lib.contents["v1"]
            comment_id = lib.comments["c1"]
            report = await repo.create(
                session,
                title="报告",
                markdown=f"[[c:{content_id}, m:{comment_id}, c:99999]]",
                dataset_id=lib.dataset_a,
                conversation_id=conversation.id,
                source="agent",
                now=NOW + 1,
            )
            report_id = report.id
            assert (
                report.basis is not None
                and report.basis["contents"] == 3
                and report.basis["comments"] == 5
            )
            assert await repo.new_since(session, report) == 0
            assert await repo.unknown_refs(session, report.id, [CitationRef("content", 99999)]) == [
                CitationRef("content", 99999)
            ]
            snapshots = list(
                (
                    await session.scalars(
                        select(ReportCitation).where(ReportCitation.report_id == report_id)
                    )
                ).all()
            )
            assert len(snapshots) == 2
            assert (
                next(item for item in snapshots if item.kind == "comment").content_id == content_id
            )
            await repo_datasets.add_to_dataset(
                session, lib.dataset_a, [lib.contents["v4"]], None, NOW + 2
            )
            assert await repo.new_since(session, report) == 1
            assert (await cleanup.impact_of_delete(session, lib.dataset_a)).reports == 1  # type: ignore[union-attr]
            await session.execute(delete(Content).where(Content.id == content_id))
            await repo.update(
                session, report_id, base_version=1, source="user", conversation_id=None, now=NOW + 3
            )
            assert (
                await repo.unknown_refs(session, report_id, [CitationRef("content", content_id)])
                == []
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ReportCitation)
                    .where(ReportCitation.report_id == report_id)
                )
                == 2
            )
            with pytest.raises(repo.VersionConflict):
                await repo.update(
                    session,
                    report_id,
                    base_version=1,
                    source="user",
                    conversation_id=None,
                    now=NOW + 4,
                )
            for version in range(2, 52):
                await repo.update(
                    session,
                    report_id,
                    base_version=version,
                    markdown="无引用",
                    source="user",
                    conversation_id=None,
                    now=NOW + version + 2,
                )
            revisions = await repo.revisions(session, report_id)
            assert (
                len(revisions) == 50 and revisions[0].version == 52 and revisions[-1].version == 3
            )
            assert await session.scalar(select(func.count()).select_from(ReportCitation)) == 0
            await session.delete(conversation)
            await session.flush()
            await session.refresh(report)
            assert report.created_in_conversation_id is None
            await cleanup.delete_all_collected(session)
            await session.refresh(report)
            assert report.dataset_id is None and await repo.new_since(session, report) is None
            await repo.delete(session, report_id)
            assert await session.scalar(select(func.count()).select_from(ReportRevision)) == 0
            assert await session.get(Report, report_id) is None
    finally:
        await db.close()
