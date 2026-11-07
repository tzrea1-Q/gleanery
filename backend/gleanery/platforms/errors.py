"""平台层抛给执行器的异常。执行器按规则转移任务与平台状态。"""

from __future__ import annotations

from gleanery.platforms.types import RiskVerdict


class FetchError(Exception):
    pass


class RiskDetected(FetchError):
    """风控信号或登录态失效，立即停止，不重试。"""

    def __init__(self, verdict: RiskVerdict) -> None:
        super().__init__(f"{verdict.kind}: {verdict.signal}")
        self.verdict = verdict


class PageChanged(FetchError):
    """页面改版：选择器超时、连续 3 次没等到预期响应、响应不空却解析不出条目等。

    `detail` 只写本地日志，不进界面。
    """

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class BrowserDisconnected(FetchError):
    """Chrome 进程退出或 CDP 断开。不冷却。"""


class TransientError(FetchError):
    """普通网络错误，执行器重试 2 次（间隔 5 秒、15 秒）。"""


class ProfileInUse(FetchError):
    """专用配置目录被其他 Chrome 占用；只提示，不强行接管。"""
