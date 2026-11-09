#!/usr/bin/env python3
"""提交前和 CI 上的泄露扫描。

`--staged` 只看暂存区新增的行，由 pre-commit 钩子调用；`--all` 扫全部跟踪文件，由 `just check` 和 CI 调用。
通用规则写在这里；维护者的私有禁写词放在主检出的 `.private/forbidden.txt`，没有这个文件就只跑通用规则。
发现问题只报位置和规则名，不打印命中的内容，免得 CI 日志把它公开出去。
确认是误报时，在那一行加上 `leak-scan: allow`。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

RULES = {
    "本机路径": r"/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|/var/folders/|/private/tmp/",
    "个人邮箱": r"[A-Za-z0-9._%+-]+@(?:gmail|qq|163|126|foxmail|outlook|hotmail|yahoo|icloud)\.com",
    "API Key": r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}|\bAKIA[0-9A-Z]{16}\b",
    "私钥": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Cookie 值": r"(?:SESSDATA|bili_jct|web_session|z_c0|__zse_ck)=[A-Za-z0-9%._-]{8,}",
}
SKIP = {"backend/uv.lock", "frontend/pnpm-lock.yaml", ".githooks/leak-scan.py"}
ALLOW_MARK = "leak-scan: allow"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def private_rules() -> dict[str, re.Pattern[str]]:
    common = pathlib.Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    path = common.parent / ".private" / "forbidden.txt"
    if not path.is_file():
        return {}
    rules = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern = line[3:] if line.startswith("re:") else re.escape(line)
        rules[f"私有禁写词第 {n} 行"] = re.compile(pattern)
    return rules


def staged_lines() -> list[tuple[str, int, str]]:
    """暂存区里新增的行：(路径, 行号, 内容)。"""
    out = []
    path, lineno = "", 0
    diff = git("diff", "--cached", "--no-color", "--no-ext-diff", "-U0", "--diff-filter=ACMR")
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("@@"):
            lineno = int(re.search(r"\+(\d+)", line).group(1))
        elif line.startswith("+") and path:
            out.append((path, lineno, line[1:]))
            lineno += 1
    return out


def tracked_lines() -> list[tuple[str, int, str]]:
    out = []
    for path in git("ls-files", "-z").split("\0"):
        file = pathlib.Path(path)
        if not path or not file.is_file():
            continue
        data = file.read_bytes()
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", "ignore").splitlines(), 1):
            out.append((path, n, line))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--all", action="store_true")
    args = parser.parse_args()

    rules = {name: re.compile(p) for name, p in RULES.items()} | private_rules()
    lines = staged_lines() if args.staged else tracked_lines()
    findings = [
        f"{path}:{n} {name}"
        for path, n, text in lines
        if path not in SKIP and ALLOW_MARK not in text
        for name, pattern in rules.items()
        if pattern.search(text)
    ]
    if findings:
        print("泄露扫描发现问题（不显示命中的内容）：", file=sys.stderr)
        print("\n".join(f"  {f}" for f in findings), file=sys.stderr)
        print(f"改掉这些内容；确认是误报时在该行加上 `{ALLOW_MARK}`。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
