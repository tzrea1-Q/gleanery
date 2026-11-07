from __future__ import annotations

import hashlib
import re
from typing import Any

from gleanery.platforms.types import Capture

_IDS = {"mid", "uid", "user_id", "author_id", "login_mid", "userid", "red_id", "redid"}
"""`login_mid` 是登录账号自己的 UID（播放器接口里），2026-11-01 录制时发现。
小红书的 `user_id` 是 24 位十六进制，SSR 里写成 `userId`；`red_id` 是小红书号。"""
_NAMES = {"uname", "nickname", "nick_name", "name", "author"}
_TEXT = {
    "title",
    "desc",
    "description",
    "message",
    "content",
    "signature",
    "sign",
    "display_title",
    "part",
}
_CURSORS = {
    "w_rid",
    "wts",
    "pagination_str",
    "next_offset",
    "cursor",
    "xsec_token",
    "token",
    "login_mid_hash",
    # 2026-11-01 录制时发现：搜索与评论的会话标识、登录账号最近播放的视频。
    "seid",
    "from_track_id",
    "session_id",
    "last_play_cid",
    # 小红书：搜索会话标识，SSR 里驼峰写法的 token。
    "search_id",
    "xsectoken",
}
_NAME_KEYED = {"at_name_to_mid", "at_name_to_mid_str"}
"""以昵称为键的映射（评论里 @ 的人），键也要换。"""
_QUERY_PUBLIC = {
    "aid",
    "cid",
    "oid",
    "bvid",
    "rpid",
    "root",
    "parent",
    "type",
    "pn",
    "ps",
    "page",
    # B 站搜索的发布时间筛选（秒级时间戳），测试要核对它与时间范围对得上。
    "pubtime_begin_s",
    "pubtime_end_s",
    # 小红书评论接口的笔记与根评论 ID（公开内容标识，解析器靠根评论 ID 串起二级评论）。
    "note_id",
    "root_comment_id",
    "num",
}
_PROVINCES = ("北京", "上海", "广东", "浙江", "四川", "湖北")
_HEADERS = {"content-type", "retry-after", "verifytype", "verifyuuid"}
_IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
"""本机出口 IP：B 站的 `ip_info.ip`、`zone_ip`、搜索结果里的 `client_ip` 等，2026-11-01 录制时发现。"""
_HEX24 = re.compile(r"[0-9a-f]{24}")
_SPECIAL = re.compile(r"\[[^\]\n]{1,40}\]|\n|@[^\s@\[\]：:，,。!！?？]+")


def redact(capture: Capture, salt: str = "gleanery-fixture-v1", trim: int | None = None) -> Capture:
    names: dict[str, str] = {}

    def digest(value: str) -> str:
        return hashlib.sha256((salt + "\0" + value).encode()).hexdigest()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _NAMES and isinstance(item, str) and item and item not in names:
                    number = len(names)
                    label = ""
                    while True:
                        label = chr(65 + number % 26) + label
                        number = number // 26 - 1
                        if number < 0:
                            break
                    names[item] = "用户" + label
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    def text(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            token = match.group()
            if token.startswith("@"):
                return "@" + names.get(token[1:], "用户" + digest(token[1:])[:8])
            return token

        parts = _SPECIAL.split(value)
        matches = list(_SPECIAL.finditer(value))
        result = ""
        for index, part in enumerate(parts):
            result += "文" * len(part)
            if index < len(matches):
                result += replace(matches[index])
        return result

    def transform(value: Any, key: str = "") -> Any:
        key = key.lower()
        # 对象形态的 cursor（如 B 站评论的 `data.cursor`）带 is_end 等分页信息，逐字段处理。
        if key in _CURSORS and value is not None and not isinstance(value, (dict, list)):
            return "REDACTED-" + digest(str(value))[:12]
        if key in _IDS and isinstance(value, (str, int)) and not isinstance(value, bool):
            original = str(value)
            if _HEX24.fullmatch(original):
                return digest(original)[:24]
            if original.isdigit():
                number = str(
                    (int(digest(original), 16) % (9 * 10 ** (len(original) - 1)))
                    + 10 ** (len(original) - 1)
                )
                return int(number) if isinstance(value, int) else number
            return "user-" + digest(original)[:12]
        if key == "ip_info" and isinstance(value, dict):
            # 播放器接口按出口 IP 给出的本机属地，整块换成固定值。
            return {k: ("REDACTED-IP" if isinstance(v, str) else 0) for k, v in value.items()}
        if key in _NAME_KEYED and isinstance(value, dict):
            return {
                names.get(k, "用户" + digest(k)[:8]): transform(v, "mid") for k, v in value.items()
            }
        if key == "jump_url" and isinstance(value, dict):
            # 评论正文里自动加链接的词，键就是正文片段；BV 号等 ASCII 键保留。
            return {(k if k.isascii() else text(k)): transform(v, k) for k, v in value.items()}
        if isinstance(value, dict):
            return {k: transform(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [transform(item) for item in (value[:trim] if trim is not None else value)]
        if not isinstance(value, str) or not value:
            return value
        if key in _NAMES:
            return names[value]
        if _IPV4.search(value):
            return _IPV4.sub("REDACTED-IP", value)
        if key in {"ip_location", "location"}:
            prefix = re.match(r"^IP属地[：:]\s*", value)
            province = _PROVINCES[int(digest(value), 16) % len(_PROVINCES)]
            return (prefix.group() if prefix else "") + province
        if re.search(r"https?://|^//", value, re.I):
            return "https://example.invalid/" + digest(value)[:12]
        if key == "tag":
            # B 站搜索结果的逗号分隔标签串：逐个标签替换，保留逗号，解析器测试要靠它切分。
            return ",".join(text(tag) for tag in value.split(","))
        if _HEX24.fullmatch(value):
            # 小红书的笔记 ID、评论 ID 是公开的，解析器靠它们去重和挂父子关系，不能当长文本换掉。
            return value
        if key in _TEXT or len(value) >= 24:
            return text(value)
        return value

    data = capture.model_dump()
    collect(data["body"])
    data["body"] = transform(data["body"])
    data["query"] = {
        k: v
        if k.lower() in _QUERY_PUBLIC
        and (
            (v.isascii() and v.isdigit())
            or (k.lower() == "bvid" and re.fullmatch(r"BV[0-9A-Za-z]{10}", v))
            or _HEX24.fullmatch(v)
        )
        else transform(v, k)
        if k.lower() in _IDS
        else "REDACTED-" + digest(v)[:12]
        for k, v in capture.query.items()
    }
    data["headers"] = {k.lower(): v for k, v in capture.headers.items() if k.lower() in _HEADERS}
    return Capture.model_validate(data)
