import { useEffect, useState } from "react";
import { usePlatformAction, usePlatforms } from "@/api/queries-platform";
import { PlatformTag, platformName } from "@/components/common/PlatformTag";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

const states = {
  normal: "正常",
  cooldown: "冷却中",
  locked: "已锁定",
  login_required: "需要登录",
  quota_exhausted: "今日额度用尽",
  page_changed: "页面改版待确认",
};
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

const stateDots: Record<keyof typeof states, string> = {
  normal: "bg-success",
  cooldown: "bg-warning",
  locked: "bg-destructive",
  login_required: "bg-warning",
  quota_exhausted: "bg-warning",
  page_changed: "bg-warning",
};

/** 左栏收成图标栏时，只留每个平台的状态点。 */
export function PlatformDots() {
  const platforms = usePlatforms();
  return (
    <div className="hidden flex-col items-center gap-2 py-1 group-data-[collapsible=icon]:flex">
      {platforms.data?.map((p) => (
        <span
          key={p.platform}
          aria-hidden
          title={`${platformName(p.platform)}：${states[p.state]}`}
          className={`size-2 rounded-full ${stateDots[p.state]}`}
        />
      ))}
    </div>
  );
}

export function PlatformPanel() {
  const platforms = usePlatforms();
  const action = usePlatformAction();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section aria-label="平台账号" className="space-y-1.5 group-data-[collapsible=icon]:hidden">
      <h2 className="px-1 text-xs text-muted-foreground">平台账号</h2>
      {platforms.isError && (
        <p role="alert" className="text-xs text-destructive">
          无法加载平台状态
        </p>
      )}
      {platforms.data?.map((p) => {
        const until =
          p.state === "cooldown" ? p.cooldown_until : p.state === "locked" ? p.locked_until : null;
        const minutes = until === null ? null : Math.max(0, Math.ceil((until - now) / 60000));
        const name = platformName(p.platform);
        return (
          <section
            key={p.platform}
            aria-label={name}
            className="space-y-1.5 rounded-2xl bg-muted p-2.5 text-xs text-muted-foreground"
          >
            <h3
              aria-label={`${name} · ${states[p.state]}`}
              className="flex items-center gap-1.5 text-foreground"
            >
              <PlatformTag platform={p.platform} />
              <span aria-hidden className={`size-1.5 rounded-full ${stateDots[p.state]}`} />
              <span className="min-w-0 truncate">{states[p.state]}</span>
              <span title="今日额度" className="ml-auto text-muted-foreground tabular-nums">
                {p.quota_used} / {p.daily_quota}
              </span>
            </h3>
            <>
              {minutes !== null && (
                <p>
                  剩余
                  {until !== null && until - now < 60000 ? "不到 1 分钟" : `约 ${minutes} 分钟`}
                </p>
              )}
              {p.reason && <p>{reasonText(p.reason)}</p>}
              {p.last_probe_at !== null && (
                <p className="truncate" title={p.last_probe_detail ?? undefined}>
                  探活{p.last_probe_ok ? "成功" : "失败"} · {formatDateTime(p.last_probe_at)}
                </p>
              )}
              {p.login.browser === "chromium" && <p>未找到本机 Chrome，正在用 Chromium</p>}
              {p.login.phase !== "idle" && (
                <p role="status">
                  扫码登录：{phases[p.login.phase]}
                  {p.login.message && ` · ${p.login.message}`}
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                <Button
                  size="xs"
                  variant="outline"
                  disabled={
                    action.isPending ||
                    p.login.phase === "waiting_scan" ||
                    p.login.phase === "verifying"
                  }
                  onClick={() => action.mutate({ platform: p.platform, action: "login" })}
                >
                  扫码登录
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  disabled={action.isPending}
                  onClick={() => action.mutate({ platform: p.platform, action: "probe" })}
                >
                  探活
                </Button>
                {p.state === "locked" && (
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={action.isPending}
                    onClick={() => action.mutate({ platform: p.platform, action: "unlock" })}
                  >
                    解锁
                  </Button>
                )}
                {p.state === "page_changed" && (
                  <>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={action.isPending}
                      onClick={() =>
                        action.mutate({ platform: p.platform, action: "accept-page-change" })
                      }
                    >
                      仍然继续
                    </Button>
                    <p>页面可能已变化，继续采集可能导致数据不完整。</p>
                  </>
                )}
              </div>
              {action.isError && (
                <p role="alert" className="text-destructive">
                  {action.error.message}
                </p>
              )}
            </>
          </section>
        );
      })}
    </section>
  );
}
