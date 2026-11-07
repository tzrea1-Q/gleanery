import { useEffect, useState } from "react";
import { usePlatformAction, usePlatforms } from "@/api/queries-platform";
import type { components } from "@/api/schema";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { PlatformTag, platformName } from "@/components/common/PlatformTag";
import { StatusBadge, type StatusTone } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";

type Platform = components["schemas"]["PlatformOut"];
type Group = "action" | "limited" | "normal";

const states: Record<Platform["state"], { label: string; group: Group; tone: StatusTone }> = {
  normal: { label: "正常", group: "normal", tone: "success" },
  cooldown: { label: "冷却中", group: "limited", tone: "warning" },
  quota_exhausted: { label: "今日额度用尽", group: "limited", tone: "warning" },
  locked: { label: "已锁定", group: "action", tone: "danger" },
  login_required: { label: "需要登录", group: "action", tone: "danger" },
  page_changed: { label: "页面改版待确认", group: "action", tone: "danger" },
};
const groupOrder: Group[] = ["action", "limited", "normal"];
const phases = {
  idle: "",
  waiting_scan: "等待扫码",
  verifying: "验证中",
  succeeded: "成功",
  failed: "失败",
  timeout: "超时",
};

// reason 是后端记下的风控信号或改版原因，原样显示用户看不懂。
function reasonText(reason: string) {
  if (reason === "http_412") return "原因：请求被平台拦截（HTTP 412）";
  if (reason === "v_voucher") return "原因：平台要求人机验证";
  if (reason === "risk_and_login") return "原因：触发风控且登录失效";
  if (reason === "nav_not_login" || reason === "code_-101") return "原因：登录已失效";
  if (reason.startsWith("code_")) return `原因：平台返回风控码 ${reason.slice(5)}`;
  return `原因：${reason}`;
}

/** 侧栏入口上的提醒。冷却和额度用尽会自己恢复，只数要用户动手的平台。 */
export function PlatformAttention() {
  const platforms = usePlatforms();
  const count = platforms.data?.filter((p) => states[p.state].group === "action").length ?? 0;
  if (!count) return null;
  return (
    <>
      <span className="sr-only">，{count} 个平台需要处理</span>
      <span
        aria-hidden
        className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-attention-muted px-1 text-xs font-medium text-attention tabular-nums group-data-[collapsible=icon]:hidden"
      >
        {count}
      </span>
      <span
        aria-hidden
        className="absolute top-1 right-1 hidden size-2 rounded-full bg-attention group-data-[collapsible=icon]:block"
      />
    </>
  );
}

function CheckLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right tabular-nums">{children}</dd>
    </div>
  );
}

function PlatformCard({ platform: p, now }: { platform: Platform; now: number }) {
  const action = usePlatformAction();
  const run = (name: Parameters<typeof action.mutate>[0]["action"]) =>
    action.mutate({ platform: p.platform, action: name });
  const name = platformName(p.platform);
  const state = states[p.state];
  const until =
    p.state === "cooldown" ? p.cooldown_until : p.state === "locked" ? p.locked_until : null;
  const minutes = until === null ? null : Math.max(0, Math.ceil((until - now) / 60000));
  const loggingIn = p.login.phase === "waiting_scan" || p.login.phase === "verifying";
  return (
    <section aria-label={name} className="flex flex-col gap-4 rounded-2xl bg-card p-5">
      <h2
        aria-label={`${name} · ${state.label}`}
        className="flex items-center justify-between gap-2"
      >
        <PlatformTag platform={p.platform} />
        <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
      </h2>
      <div className="space-y-1.5">
        <p className="flex items-baseline gap-1 text-3xl font-semibold tracking-tight tabular-nums">
          {p.quota_used}
          <span className="text-sm font-normal tracking-normal text-muted-foreground">
            / {p.daily_quota} 今日额度
          </span>
        </p>
        <Progress
          aria-label={`${name}今日额度`}
          className="h-1.5 bg-muted"
          value={p.daily_quota ? Math.min(100, (p.quota_used / p.daily_quota) * 100) : 0}
        />
      </div>
      <dl className="space-y-1 text-xs">
        <CheckLine label="等待中的任务">{p.queue_length}</CheckLine>
        <CheckLine label="最近探活">
          {p.last_probe_at === null ? (
            "暂无"
          ) : (
            <span title={p.last_probe_detail ?? undefined}>
              {p.last_probe_ok ? "成功" : "失败"} · {formatDateTime(p.last_probe_at)}
            </span>
          )}
        </CheckLine>
        {minutes !== null && until !== null && (
          <CheckLine label="恢复时间">
            剩余{until - now < 60000 ? "不到 1 分钟" : `约 ${minutes} 分钟`}
          </CheckLine>
        )}
      </dl>
      {(p.reason || p.login.browser === "chromium" || p.login.phase !== "idle") && (
        <div className="space-y-1 rounded-xl bg-muted/60 px-3 py-2 text-xs text-muted-foreground dark:bg-muted/40">
          {p.reason && <p>{reasonText(p.reason)}</p>}
          {p.login.phase !== "idle" && (
            <p role="status">
              扫码登录：{phases[p.login.phase]}
              {p.login.message && ` · ${p.login.message}`}
            </p>
          )}
          {p.login.browser === "chromium" && <p>未找到本机 Chrome，正在用 Chromium</p>}
        </div>
      )}
      {p.state === "page_changed" && (
        <p className="text-xs text-muted-foreground">
          页面可能已变化，继续采集可能导致数据不完整。
        </p>
      )}
      {action.isError && <Notice>{action.error.message}</Notice>}
      <div className="mt-auto flex flex-wrap gap-1.5">
        <Button
          variant="outline"
          size="sm"
          disabled={action.isPending || loggingIn}
          onClick={() => run("login")}
        >
          扫码登录
        </Button>
        <Button variant="ghost" size="sm" disabled={action.isPending} onClick={() => run("probe")}>
          探活
        </Button>
        {p.state === "locked" && (
          <Button
            variant="outline"
            size="sm"
            disabled={action.isPending}
            onClick={() => run("unlock")}
          >
            解锁
          </Button>
        )}
        {p.state === "page_changed" && (
          <Button
            variant="outline"
            size="sm"
            disabled={action.isPending}
            onClick={() => run("accept-page-change")}
          >
            仍然继续
          </Button>
        )}
      </div>
    </section>
  );
}

export function PlatformAccounts() {
  const platforms = usePlatforms();
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState<Group | "">("");
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
  const all = platforms.data ?? [];
  const attention = all.filter((p) => states[p.state].group === "action").length;
  const shown = all
    .filter((p) => platformName(p.platform).toLowerCase().includes(search.trim().toLowerCase()))
    .filter((p) => !group || states[p.state].group === group)
    // 要处理的排在最前，平台再多也不用翻找。
    .sort(
      (a, b) =>
        groupOrder.indexOf(states[a.state].group) - groupOrder.indexOf(states[b.state].group),
    );
  return (
    <div className="h-full space-y-5 overflow-y-auto px-6 py-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">平台账号</h1>
          <p className="text-muted-foreground">
            {platforms.data
              ? `共 ${all.length} 个平台${attention ? `，${attention} 个需要处理` : ""}`
              : "各平台的登录和采集额度都在这里"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FormSelect
            aria-label="状态筛选"
            className="w-32 rounded-full border-0 bg-card shadow-none dark:bg-card"
            value={group}
            onValueChange={(value) => setGroup(value as Group | "")}
            options={[
              { value: "", label: "全部状态" },
              { value: "action", label: "需要处理" },
              { value: "limited", label: "暂时受限" },
              { value: "normal", label: "正常" },
            ]}
          />
          <Input
            aria-label="搜索平台"
            placeholder="搜索平台"
            className="w-48 rounded-full border-0 bg-card shadow-none dark:bg-card"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </div>
      {platforms.isPending ? (
        <div
          role="status"
          aria-label="正在加载平台状态…"
          className="grid grid-cols-[repeat(auto-fill,minmax(min(20rem,100%),1fr))] gap-3"
        >
          <Skeleton className="h-64 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : platforms.isError ? (
        <Notice>无法加载平台状态</Notice>
      ) : shown.length ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(20rem,100%),1fr))] gap-3">
          {shown.map((platform) => (
            <PlatformCard key={platform.platform} platform={platform} now={now} />
          ))}
        </div>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>没有符合条件的平台</EmptyTitle>
            <EmptyDescription>换个关键词或状态试试</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}
