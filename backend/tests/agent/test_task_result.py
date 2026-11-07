from gleanery.agent.tools import task_result
from gleanery.api.schemas_collect import TaskOut
from gleanery.collect.types import TaskProgress


def view(phase: str) -> TaskOut:
    return TaskOut(
        id=1,
        plan_id=1,
        dataset_id=1,
        platform="bili",
        status="running" if phase != "done" else "completed",
        reason=None,
        wait_reason=None,
        wait_until=None,
        queue_position=None,
        snapshot={"section": {}},
        progress=TaskProgress.model_validate(
            {"phase": phase, "keyword": "咖啡", "comments": 137, "last_log": "已采 BV1"}
        ),
        created_at=0,
        started_at=0,
        finished_at=None,
    )


def test_done_task_hides_keyword_and_labels_comments() -> None:
    result = task_result(view("done"))
    assert "keyword" not in result["progress"] and "snapshot" not in result
    assert result["progress"]["comments_including_replies"] == 137
    assert "comments" not in result["progress"]
    assert result["untrusted"] == {"last_log": "已采 BV1"}


def test_searching_task_keeps_keyword() -> None:
    assert task_result(view("search"))["progress"]["keyword"] == "咖啡"
