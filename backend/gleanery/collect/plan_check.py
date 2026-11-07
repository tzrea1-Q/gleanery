from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.schemas_collect import PlanIssue
from gleanery.collect.estimate import estimate_task_seconds
from gleanery.collect.plan import PlanBody
from gleanery.collect.service import CollectService
from gleanery.collect.settings import load_rate_limits
from gleanery.platforms.links import parse_link
from gleanery.platforms.types import ContentRef, Platform
from gleanery.store.models import Content, Dataset

_PLATFORM_NAMES: dict[Platform, str] = {"bili": "B 站", "xhs": "小红书"}
# 这段提示同时给 Agent 和计划卡片看，要能直接念给用户。
_WAIT_TEXT = {
    "queue": "前面还有任务",
    "cooldown": "平台冷却中",
    "locked": "平台已锁定，需要你在平台面板解锁",
    "login_required": "需要先扫码登录",
    "quota_exhausted": "今日额度已用尽",
    "page_changed": "上次采集遇到页面改版，需要你先处理",
    "min_interval": "距上个任务的间隔还不够",
    "warmup": "登录后预热中",
    "blocked_by_risk_pause": "有风控暂停的任务等你处理",
}


def _not_ready(reason: str | None, until: int | None, now: int) -> str:
    text = _WAIT_TEXT.get(reason or "", "平台暂时不能采集")
    if until is None:
        return f"{text}，任务会排队等待"
    minutes = max(1, -(-(until - now) // 60000))
    return f"{text}，任务会排队，约 {minutes} 分钟后开始"


async def estimates(session: AsyncSession, body: PlanBody) -> dict[str, int]:
    return {
        section.platform: estimate_task_seconds(
            section, await load_rate_limits(session, section.platform)
        )
        for section in body.sections
    }


async def check(
    session: AsyncSession, body: PlanBody, collect: CollectService, now: int
) -> tuple[list[PlanIssue], dict[Platform, list[ContentRef]]]:
    issues: list[PlanIssue] = []
    if (
        body.target_dataset_id is not None
        and await session.get(Dataset, body.target_dataset_id) is None
    ):
        issues.append(
            PlanIssue(
                code="DATASET_NOT_FOUND",
                message="目标数据集已删除，请改为新建或选其他数据集",
                platform=None,
                severity="error",
            )
        )
    resolved: dict[Platform, list[ContentRef]] = {}
    seen: set[Platform] = set()
    for section in body.sections:
        platform = section.platform

        def add(
            code: str, message: str, severity: str = "error", platform: Platform = platform
        ) -> None:
            issues.append(
                PlanIssue(
                    code=code,
                    message=message,
                    platform=platform,
                    severity="warning" if severity == "warning" else "error",
                )
            )

        if platform in seen:
            add("DUPLICATE_PLATFORM", "同一平台不能有多个分段")
        seen.add(platform)
        if (not section.keywords and not section.targets) or (
            section.keywords and not section.quantity
        ):
            add("EMPTY_SECTION", "分段缺少目标或关键词数量为零")
        limits = await load_rate_limits(session, platform)
        count = section.quantity + len(section.targets)
        if count > limits.task_hard_cap:
            add("HARD_CAP_EXCEEDED", f"超过单任务上限 {limits.task_hard_cap}")
        refs = resolved.setdefault(platform, [])
        for target in section.targets:
            ref = None
            if target.startswith("content:"):
                identifier = target.removeprefix("content:")
                content = (
                    await session.get(Content, int(identifier)) if identifier.isdecimal() else None
                )
                if content is not None and content.platform == platform:
                    ref = ContentRef(
                        platform=platform,
                        platform_id=content.platform_id,
                        url=content.url,
                        ext={
                            key: content.ext[key]
                            for key in ("xsec_token", "xsec_source")
                            if key in content.ext
                        },
                    )
            else:
                with suppress(ValueError):
                    ref = parse_link(platform, target)
            safe_target = target.split("?", 1)[0].split("#", 1)[0]
            if ref is None:
                add("UNRESOLVABLE_LINK", f"无法解析指定内容：{safe_target}")
                continue
            if platform == "xhs" and not ref.ext.get("xsec_token"):
                content = await session.scalar(
                    select(Content).where(
                        Content.platform == platform, Content.platform_id == ref.platform_id
                    )
                )
                if content is not None:
                    ref.ext = {
                        **{
                            key: content.ext[key]
                            for key in ("xsec_token", "xsec_source")
                            if key in content.ext
                        },
                        **{key: value for key, value in ref.ext.items() if value},
                    }
                if not ref.ext.get("xsec_token"):
                    add(
                        "UNRESOLVABLE_LINK",
                        f"{safe_target} 缺少 xsec_token：请从小红书网页或 App 复制完整的分享链接",
                    )
                    continue
            refs.append(ref)
        if collect.runtime is None or platform not in collect.runtime.platforms:
            add("PLATFORM_UNSUPPORTED", "该平台没有可用的采集运行时")
            continue
        remaining = await collect.quota_remaining(session, platform)
        if count > remaining:
            add("QUOTA_EXCEEDED", "超出今日剩余额度，超出部分明天继续", "warning")
        view = await collect.platform_view(session, platform)
        if view.state != "normal" or view.wait_reason is not None:
            # 两个平台的计划里要分得清是哪个平台在等。
            add(
                "PLATFORM_NOT_READY",
                f"{_PLATFORM_NAMES[platform]}：{_not_ready(view.wait_reason, view.wait_until, now)}",
                "warning",
            )
    return issues, resolved
