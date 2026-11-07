import { useState } from "react";
import {
  useCollectSettings,
  useResetCollectSettings,
  useRiskEvents,
  useUpdateCollectSettings,
} from "@/api/queries-platform";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { riskNotificationKey } from "@/lib/notify";

type Platform = "bili" | "xhs";
type Limits = Omit<
  components["schemas"]["RateLimits"],
  "page_interval" | "comment_page_interval" | "long_rest"
> & { page_interval: number[]; comment_page_interval: number[]; long_rest: number[] };
type Update = components["schemas"]["RateLimitsUpdate"];
const names = { bili: "B 站", xhs: "小红书" };
const intervals = [
  ["page_interval", "页面间隔"],
  ["comment_page_interval", "评论页间隔"],
] as const;
const numbers = [
  ["task_default_limit", "单任务默认数量"],
  ["daily_quota", "每日额度"],
  ["risk_cooldown_minutes", "风控冷却（分钟）"],
  ["min_task_gap_minutes", "任务最小间隔（分钟）"],
] as const;

function RateForm({
  platform,
  current,
  defaults,
}: {
  platform: Platform;
  current: Limits;
  defaults: Limits;
}) {
  const [values, setValues] = useState<Update>({
    page_interval: [current.page_interval[0], current.page_interval[1]],
    comment_page_interval: [current.comment_page_interval[0], current.comment_page_interval[1]],
    task_default_limit: current.task_default_limit,
    daily_quota: current.daily_quota,
    risk_cooldown_minutes: current.risk_cooldown_minutes,
    min_task_gap_minutes: current.min_task_gap_minutes,
  });
  const save = useUpdateCollectSettings();
  const reset = useResetCollectSettings();
  const [errorField, setErrorField] = useState<string | null>(null);
  return (
    <form
      className="space-y-2 rounded border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        const field =
          intervals.find(([key]) => {
            const pair = values[key]!;
            const floor =
              key === "page_interval"
                ? defaults.page_interval_floor
                : defaults.comment_page_interval[0] / 2;
            return pair[0] < floor || pair[0] > pair[1];
          })?.[0] ?? null;
        setErrorField(field);
        save.mutate({ platforms: { [platform]: values } });
      }}
    >
      <h3 className="font-semibold">{names[platform]}</h3>
      {intervals.map(([key, label]) => (
        <div key={key}>
          <div>
            {label}（秒，默认 {defaults[key].join("–")}）
          </div>
          {([0, 1] as const).map((index) => (
            <label key={index} className="mr-2">
              {label}
              {index === 0 ? "下界" : "上界"}
              <input
                className="ml-1 w-20 rounded border p-1"
                type="number"
                step="any"
                required
                value={values[key]?.[index] ?? ""}
                onChange={(e) => {
                  const pair: [number, number] = [...values[key]!];
                  pair[index] = e.target.valueAsNumber;
                  setValues({ ...values, [key]: pair });
                }}
              />
            </label>
          ))}
          {save.isError && errorField === key && <p role="alert">{save.error.message}</p>}
        </div>
      ))}
      {numbers.map(([key, label]) => (
        <label key={key} className="block">
          {label}（默认 {defaults[key]}）
          <input
            className="ml-2 w-24 rounded border p-1"
            type="number"
            step={key === "task_default_limit" || key === "daily_quota" ? "1" : "any"}
            min={key === "task_default_limit" || key === "daily_quota" ? "1" : "0"}
            required
            value={values[key] ?? ""}
            onChange={(e) => setValues({ ...values, [key]: e.target.valueAsNumber })}
          />
        </label>
      ))}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || reset.isPending}>
          保存
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={save.isPending || reset.isPending}
          onClick={() =>
            reset.mutate(platform, {
              onSuccess: (data) => {
                const c = data.platforms[platform].current;
                setValues({
                  page_interval: [c.page_interval[0], c.page_interval[1]],
                  comment_page_interval: [c.comment_page_interval[0], c.comment_page_interval[1]],
                  task_default_limit: c.task_default_limit,
                  daily_quota: c.daily_quota,
                  risk_cooldown_minutes: c.risk_cooldown_minutes,
                  min_task_gap_minutes: c.min_task_gap_minutes,
                });
                save.reset();
              },
            })
          }
        >
          恢复默认
        </Button>
      </div>
      {save.isError && !errorField && <p role="alert">{save.error.message}</p>}
      {reset.isError && <p role="alert">{reset.error.message}</p>}
    </form>
  );
}

function RiskEvents() {
  const [platform, setPlatform] = useState<Platform | "">("");
  const events = useRiskEvents(platform);
  return (
    <section aria-label="风控事件">
      <h3 className="font-semibold">风控事件</h3>
      <label>
        平台筛选{" "}
        <select
          className="rounded border p-1"
          value={platform}
          onChange={(e) => setPlatform(e.target.value as Platform | "")}
        >
          <option value="">全部平台</option>
          <option value="bili">B 站</option>
          <option value="xhs">小红书</option>
        </select>
      </label>
      {events.isError && <p role="alert">无法加载风控事件</p>}
      {events.data?.length === 0 && <p>暂无风控事件</p>}
      {events.data?.map((event) => (
        <details key={event.id} className="rounded border p-2">
          <summary>
            {new Date(event.at).toLocaleString()} · {names[event.platform]} · {event.signal} ·{" "}
            {event.task_id === null ? "无任务" : `任务 ${event.task_id}`} · 已采{" "}
            {event.collected_count} 条 ·{" "}
            {event.outcome === "cooldown"
              ? `冷却${event.outcome_until ? `至 ${new Date(event.outcome_until).toLocaleString()}` : "中"}`
              : event.outcome === "locked"
                ? "锁定"
                : event.outcome === "login_required"
                  ? "需要登录"
                  : event.outcome}
          </summary>
          <pre className="whitespace-pre-wrap break-all">
            {JSON.stringify(event.rate_params, null, 2)}
          </pre>
        </details>
      ))}
    </section>
  );
}

export function CollectSettings() {
  const settings = useCollectSettings();
  const update = useUpdateCollectSettings();
  const [notify, setNotify] = useState(() => localStorage.getItem(riskNotificationKey) === "true");
  const [notifyError, setNotifyError] = useState("");
  return (
    <div className="space-y-4">
      <p>改动只对之后开始的任务生效，单任务上限不可调。</p>
      {settings.isError && <p role="alert">无法加载采集设置</p>}
      {settings.data && (
        <>
          <label className="block">
            <input
              type="checkbox"
              checked={settings.data.warmup_enabled}
              disabled={update.isPending}
              onChange={(e) => update.mutate({ warmup_enabled: e.target.checked })}
            />{" "}
            登录后预热
          </label>
          {update.isError && <p role="alert">{update.error.message}</p>}
          {(["bili", "xhs"] as const).map(
            (platform) =>
              settings.data.platforms[platform] && (
                <RateForm
                  key={platform}
                  platform={platform}
                  {...settings.data.platforms[platform]}
                />
              ),
          )}
        </>
      )}
      <label className="block">
        <input
          type="checkbox"
          checked={notify}
          onChange={async (e) => {
            if (!e.target.checked) {
              localStorage.setItem(riskNotificationKey, "false");
              setNotify(false);
              setNotifyError("");
              return;
            }
            try {
              const permission =
                "Notification" in window ? await Notification.requestPermission() : "denied";
              const enabled = permission === "granted";
              localStorage.setItem(riskNotificationKey, String(enabled));
              setNotify(enabled);
              setNotifyError(enabled ? "" : "通知权限未获授权，请在浏览器或系统设置中允许通知。");
            } catch {
              localStorage.setItem(riskNotificationKey, "false");
              setNotify(false);
              setNotifyError("无法申请通知权限，请检查浏览器设置。");
            }
          }}
        />{" "}
        风控时发系统通知
      </label>
      {notifyError && <p role="alert">{notifyError}</p>}
      <RiskEvents />
    </div>
  );
}
