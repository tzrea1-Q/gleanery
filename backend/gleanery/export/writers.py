"""生成 Excel、CSV 和 Markdown。"""

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, tzinfo
from typing import Any, cast

import xlsxwriter

from gleanery.export.rows import ExportData
from gleanery.platforms.links import open_url
from gleanery.platforms.types import Platform
from gleanery.query.filters import ContentFilter
from gleanery.query.timefmt import local_datetime
from gleanery.store.models import Content

CONTENT_HEADERS = [
    "内容 ID",
    "平台",
    "链接",
    "类型",
    "标题",
    "正文",
    "作者",
    "发布时间",
    "点赞",
    "收藏",
    "评论数",
    "分享",
    "播放",
    "近似值",
    "标签",
    "完整度",
    "本地评论数",
    "字幕数",
    "加入时间",
]
COMMENT_HEADERS = [
    "评论 ID",
    "内容 ID",
    "内容标题",
    "层级",
    "回复给",
    "作者",
    "正文",
    "发布时间",
    "点赞",
    "回复数",
    "IP 属地",
]
SUBTITLE_HEADERS = ["字幕 ID", "内容 ID", "内容标题", "分 P", "语言", "AI 生成", "字数", "全文"]
FILTER_LABELS = {
    "platform": "平台",
    "keyword": "关键词",
    "author": "作者",
    "published_from": "发布日期起",
    "published_to": "发布日期止",
    "min_likes": "最低点赞",
    "min_plays": "最低播放",
    "min_comments": "最低评论",
    "completeness": "完整度",
    "has_subtitles": "有字幕",
}


KIND_TEXT = {"video": "视频", "image_text": "图文"}


def by_content(data: ExportData) -> tuple[dict[int, list[Any]], dict[int, list[Any]]]:
    comments: dict[int, list[Any]] = defaultdict(list)
    subtitles: dict[int, list[Any]] = defaultdict(list)
    for x in data.comments:
        comments[x.content_id].append(x)
    for s in data.subtitles:
        subtitles[s.content_id].append(s)
    return comments, subtitles


def local(ms: int | None, tz: tzinfo | None) -> datetime | None:
    return (
        datetime.fromtimestamp(ms / 1000, UTC).astimezone(tz).replace(tzinfo=None)
        if ms is not None
        else None
    )


def filter_text(filter: ContentFilter | None) -> str:
    values = filter.model_dump(mode="json", exclude_none=True) if filter else {}

    def describe(key: str, value: Any) -> Any:
        if key == "platform":
            return {"bili": "B 站", "xhs": "小红书"}.get(value, value)
        if key == "completeness":
            return {"summary": "仅摘要", "detail": "已详情"}.get(value, value)
        if isinstance(value, bool):
            return "是" if value else "否"
        return value

    return (
        "、".join(f"{FILTER_LABELS[k]}：{describe(k, v)}" for k, v in values.items() if v != "")
        or "无"
    )


def link(content: Content) -> str:
    return open_url(cast(Platform, content.platform), content.url, content.ext or {})


def tables(
    data: ExportData, tz: tzinfo | None, include_ext: bool
) -> list[tuple[str, list[str], list[list[Any]]]]:
    content_rows: list[list[Any]] = []
    comment_rows: list[list[Any]] = []
    subtitle_rows: list[list[Any]] = []
    comments_of, subtitles_of = by_content(data)
    for c, added in data.contents:
        comments = comments_of[c.id]
        subtitles = subtitles_of[c.id]
        ext = c.ext or {}
        content_rows.append(
            [
                c.id,
                "B 站" if c.platform == "bili" else "小红书",
                link(c),
                KIND_TEXT.get(c.kind, c.kind),
                c.title,
                c.body,
                data.authors.get(c.author_id or 0),
                local(c.published_at, tz),
                c.likes,
                c.favorites,
                c.comments,
                c.shares,
                c.plays,
                "是" if ext.get("counts_approx") else "否",
                "、".join(c.tags or []),
                "已详情" if c.completeness == "detail" else "仅摘要",
                len(comments),
                len(subtitles),
                local(added, tz),
            ]
            + (
                [
                    ext.get("coins"),
                    ext.get("danmaku"),
                    ext.get("duration"),
                    ext.get("tname"),
                    json.dumps(ext, ensure_ascii=False),
                ]
                if include_ext
                else []
            )
        )
        roots = sorted(
            (x for x in comments if x.root_platform_id is None),
            key=lambda x: (x.likes is not None, x.likes or 0, x.id),
            reverse=True,
        )
        by_platform = {x.platform_id: x for x in comments}
        replies_of: dict[str, list[Any]] = defaultdict(list)
        for x in comments:
            if x.root_platform_id is not None:
                replies_of[x.root_platform_id].append(x)
        ordered = []
        for root in roots:
            ordered.append(root)
            ordered.extend(
                sorted(
                    replies_of[root.platform_id],
                    key=lambda x: (x.published_at is None, x.published_at or 0, x.id),
                )
            )
        # 根评论没采到的回复排在最后。
        placed = {x.id for x in ordered}
        ordered.extend(x for x in comments if x.id not in placed)
        for x in ordered:
            parent = by_platform.get(x.parent_platform_id or "")
            comment_rows.append(
                [
                    x.id,
                    c.id,
                    c.title,
                    "回复" if x.root_platform_id else "一级",
                    data.authors.get(parent.author_id or 0) if parent else None,
                    data.authors.get(x.author_id or 0),
                    x.body,
                    local(x.published_at, tz),
                    x.likes,
                    x.reply_count,
                    x.ip_location,
                ]
            )
        for s in subtitles:
            subtitle_rows.append(
                [
                    s.id,
                    c.id,
                    c.title,
                    s.part_title,
                    s.lang,
                    "是" if s.ai_generated else "否",
                    len(s.text),
                    s.text,
                ]
            )
    return [
        (
            "内容",
            CONTENT_HEADERS
            + (["投币", "弹幕", "时长（秒）", "分区", "扩展字段（JSON）"] if include_ext else []),
            content_rows,
        ),
        ("评论", COMMENT_HEADERS, comment_rows),
        ("字幕", SUBTITLE_HEADERS, subtitle_rows),
    ]


def xlsx(
    data: ExportData, tz: tzinfo | None, now: int, filter: ContentFilter | None, include_ext: bool
) -> bytes:
    out = io.BytesIO()
    workbook = xlsxwriter.Workbook(out, {"in_memory": True})
    date_format = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})
    all_tables = tables(data, tz, include_ext)
    info = [
        ["数据集名", data.dataset.name],
        ["说明", data.dataset.description],
        ["导出时间", local(now, tz)],
        ["时区", str(tz or datetime.now().astimezone().tzinfo)],
        ["筛选条件", filter_text(filter)],
        *[[f"{name}条数", len(rows)] for name, _, rows in all_tables],
        ["近似值", "内容表「近似值」为“是”的行，互动数字是平台给的近似值"],
        ["截断说明", "超过 32767 字的单元格已截断，见 Markdown 导出"],
    ]
    for name, headers, rows in [*all_tables, ("说明", ["项目", "值"], info)]:
        sheet = workbook.add_worksheet(name)
        for row_index, row in enumerate([headers, *rows]):
            for col, value in enumerate(row):
                if value is None:
                    continue
                if isinstance(value, datetime):
                    sheet.write_datetime(row_index, col, value, date_format)
                elif isinstance(value, (int, float)):
                    sheet.write_number(row_index, col, value)
                else:
                    text = str(value)
                    suffix = "…（已截断，见 Markdown 导出）"
                    sheet.write_string(
                        row_index,
                        col,
                        text if len(text) <= 32767 else text[: 32767 - len(suffix)] + suffix,
                    )
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, len(rows), len(headers) - 1)
    workbook.close()
    return out.getvalue()


def csv_zip(data: ExportData, tz: tzinfo | None, include_ext: bool) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, headers, rows in tables(data, tz, include_ext):
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
            for row in [headers, *rows]:
                values = []
                for value in row:
                    if isinstance(value, datetime):
                        value = value.strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(value, str) and value.startswith(
                        ("=", "+", "-", "@", "\t", "\r")
                    ):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
            archive.writestr(name + ".csv", stream.getvalue().encode("utf-8-sig"))
    return out.getvalue()


def markdown(
    data: ExportData,
    tz: tzinfo | None,
    now: int,
    filter: ContentFilter | None,
    comment_limit: int,
    include_subtitles: bool,
) -> bytes:
    def safe(value: Any) -> str:
        return re.sub(r"(?m)^([#>])", r"\\\1", str(value or ""))

    def item(value: Any, indent: str) -> str:
        # 多行评论续行缩进到列表项内；去掉空行，免得把列表断开；行首的列表标记转义，免得变成嵌套列表
        text = re.sub(r"(?m)^(\s*)(\d*)([-+*.)])(?=\s)", r"\1\2\\\3", safe(value))
        return f"\n{indent}".join(line for line in text.splitlines() if line.strip())

    exported = local_datetime(now, tz)

    lines = [
        f"# {safe(data.dataset.name)}",
        "",
        safe(data.dataset.description),
        "",
        f"导出时间：{exported:%Y-%m-%d %H:%M}（UTC{exported.isoformat()[-6:]}）",
        f"筛选条件：{filter_text(filter)}",
        f"内容：{len(data.contents)} 条，评论：{len(data.comments)} 条，字幕：{len(data.subtitles)} 条",
        "",
    ]
    comments_of, subtitles_of = by_content(data)
    for i, (c, _) in enumerate(data.contents, 1):
        approx = "≈" if (c.ext or {}).get("counts_approx") else ""

        def count(n: int | None, prefix: str = approx) -> str:
            return f"{prefix}{n}" if n is not None else "未知"

        lines += [
            f"## {i}. {safe(c.title)}",
            "",
            f"{'B 站' if c.platform == 'bili' else '小红书'} · {safe(data.authors.get(c.author_id or 0))} · {local(c.published_at, tz) or '未知'} · 播放 {count(c.plays)} · 点赞 {count(c.likes)} · 评论 {count(c.comments)} · 收藏 {count(c.favorites)}",
            "",
            f"原文链接：{link(c)}",
            "",
            safe(c.body),
            "",
        ]
        comments = comments_of[c.id]
        roots = sorted(
            (x for x in comments if x.root_platform_id is None),
            key=lambda x: (x.likes is not None, x.likes or 0, x.id),
            reverse=True,
        )[:comment_limit]
        if roots:
            lines += ["### 评论", ""]
        for root in roots:
            lines.append(
                f"- {safe(data.authors.get(root.author_id or 0))}（点赞 {root.likes if root.likes is not None else '未知'}）：{item(root.body, '  ')}"
            )
            replies = sorted(
                (x for x in comments if x.root_platform_id == root.platform_id),
                key=lambda x: (x.published_at is None, x.published_at or 0, x.id),
            )[:5]
            for reply in replies:
                lines.append(
                    f"  - {safe(data.authors.get(reply.author_id or 0))}（点赞 {reply.likes if reply.likes is not None else '未知'}）：{item(reply.body, '    ')}"
                )
        if include_subtitles:
            for s in subtitles_of[c.id]:
                lines += [
                    "",
                    f"### 字幕：{safe(s.part_title)}（{safe(s.lang)}）",
                    "",
                    safe(s.text),
                ]
        lines.append("")
    return "\n".join(lines).encode("utf-8")
