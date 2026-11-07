from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from playwright.async_api import async_playwright

BrowserKind = Literal["chrome", "edge", "chromium"]


@dataclass(frozen=True)
class BrowserExecutable:
    path: Path
    kind: BrowserKind


async def find_browser() -> BrowserExecutable:
    home = Path.home()
    if sys.platform == "darwin":
        chrome = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        edge = [
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            home / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif sys.platform == "win32":
        roots = [
            Path(os.environ[name])
            for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
            if os.environ.get(name)
        ]
        chrome = [root / "Google/Chrome/Application/chrome.exe" for root in roots]
        edge = [root / "Microsoft/Edge/Application/msedge.exe" for root in roots]
    else:
        chrome = [
            Path(path)
            for name in ("google-chrome", "google-chrome-stable")
            if (path := shutil.which(name))
        ]
        edge = [
            Path(path)
            for name in ("microsoft-edge", "microsoft-edge-stable")
            if (path := shutil.which(name))
        ]
        chrome += [Path("/opt/google/chrome/chrome")]
        edge += [Path("/opt/microsoft/msedge/msedge")]
    for kind, candidates in (("chrome", chrome), ("edge", edge)):
        for path in candidates:
            if path.is_file():
                return BrowserExecutable(path, kind)  # type: ignore[arg-type]
    async with async_playwright() as playwright:
        path = Path(playwright.chromium.executable_path)
    if path.is_file():
        return BrowserExecutable(path, "chromium")
    raise FileNotFoundError("未找到 Chrome、Edge 或 Playwright Chromium")
