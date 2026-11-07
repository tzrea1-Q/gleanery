import { useEffect, useState } from "react";
import { useTaskAction } from "@/api/queries-collect";
import type { components } from "@/api/schema";
type Task = components["schemas"]["TaskOut"];
export const finished = (task: Task) => ["completed", "stopped", "failed"].includes(task.status);
export function duration(seconds: number) {
  return seconds < 60 ? "不到 1 分钟" : `约 ${Math.ceil(seconds / 60)} 分钟`;
}
// 已中断（app_restart）直接替换状态名，不在这里。
const reasons = {
  risk: "风控暂停",
  login_lost: "登录失效",
  user: "用户暂停",
  browser_disconnected: "浏览器或页面被关闭",
  page_changed: "页面改版",
  network: "网络错误",
};
const statuses = {
  queued: "排队中",
  running: "执行中",
  paused: "已暂停",
  completed: "已完成",
  stopped: "已停止",
  failed: "失败",
};
const waits = {
  queue: "等待前面的任务",
  cooldown: "冷却中",
  locked: "已锁定",
  login_required: "需要登录",
  quota_exhausted: "今日额度用尽，零点后继续",
  page_changed: "上次任务遇到页面改版，等你决定",
  min_interval: "等待任务间隔",
  warmup: "登录后预热",
  blocked_by_risk_pause: "等待处理风控暂停的任务",
};
export function Progress({ tasks }: { tasks: Task[] }) {
  const action = useTaskAction();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="space-y-3">
      {tasks.map((t) => (
        <section
          key={t.id}
          aria-label={`${t.platform === "bili" ? "B 站" : "小红书"}采集任务`}
          className="space-y-1 rounded border p-3"
        >
          <h4 className="font-medium">
            {t.platform === "bili" ? "B 站" : "小红书"} ·{" "}
            {t.reason === "app_restart" && t.status === "paused" ? "已中断" : statuses[t.status]}
            {(t.status === "paused" || t.status === "failed") &&
              t.reason &&
              t.reason in reasons &&
              `（${reasons[t.reason as keyof typeof reasons]}）`}
          </h4>
          {t.wait_reason && (
            <p>
              {waits[t.wait_reason]}
              {t.wait_until ? `，${duration(Math.max(0, (t.wait_until - now) / 1000))}后开始` : ""}
            </p>
          )}
          <p>
            实得 / 计划：{t.progress.processed} / {t.progress.planned} · 评论 {t.progress.comments}
            {t.platform === "bili" && ` · 字幕 ${t.progress.subtitles}`}
          </p>
          {!finished(t) && (
            <p>
              预计剩余时间：
              {t.progress.eta_seconds == null ? "未知" : duration(t.progress.eta_seconds)}
            </p>
          )}
          {t.progress.last_log && <p className="break-words">{t.progress.last_log}</p>}
          {t.reason === "risk" && t.status === "paused" && <p>本平台队列在你选择前不会继续</p>}
          {t.reason === "login_lost" && t.status === "paused" && <p>请去左栏扫码登录</p>}
          {!finished(t) && (
            <div className="flex flex-wrap gap-2">
              {t.status === "paused" ? (
                <button
                  className="rounded border p-1"
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: t.id, action: "resume" })}
                >
                  {t.reason === "risk" ? "已验证，继续（冷却后恢复）" : "继续"}
                </button>
              ) : (
                <button
                  className="rounded border p-1"
                  disabled={action.isPending}
                  onClick={() => action.mutate({ id: t.id, action: "pause" })}
                >
                  暂停
                </button>
              )}
              <button
                className="rounded border p-1"
                disabled={action.isPending}
                onClick={() => action.mutate({ id: t.id, action: "stop" })}
              >
                {t.reason === "risk" && t.status === "paused" ? "跳过剩余部分" : "停止"}
              </button>
            </div>
          )}
          {action.isError && <p role="alert">操作失败，请重试</p>}
        </section>
      ))}
    </div>
  );
}
