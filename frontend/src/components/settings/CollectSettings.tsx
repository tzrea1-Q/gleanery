import { useState } from "react";
import {
  useCollectSettings,
  useResetCollectSettings,
  useRiskEvents,
  useUpdateCollectSettings,
} from "@/api/queries-platform";
import type { components } from "@/api/schema";
import { CheckRow } from "@/components/common/CheckRow";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { PlatformTag } from "@/components/common/PlatformTag";
import { StatusBadge, type StatusTone } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { riskNotificationKey } from "@/lib/notify";
import { formatDateTime } from "@/lib/format";

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
      className="space-y-2 rounded-2xl bg-muted/60 p-4 dark:bg-muted/40"
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
      <h3 className="text-lg font-semibold tracking-tight">{names[platform]}</h3>
      {intervals.map(([key, label]) => (
        <div key={key} className="space-y-1">
          <div className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] items-center gap-2">
            <p className="text-muted-foreground">
              {label}
              <span className="ml-1 text-xs">（秒，默认 {defaults[key].join("–")}）</span>
            </p>
            {([0, 1] as const).map((index) => (
              <Input
                key={index}
                aria-label={`${label}${index === 0 ? "下界" : "上界"}`}
                placeholder={index === 0 ? "下界" : "上界"}
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
            ))}
          </div>
          {save.isError && errorField === key && <Notice>{save.error.message}</Notice>}
        </div>
      ))}
      {numbers.map(([key, label]) => (
        <FormRow
          key={key}
          label={
            <>
              {label}
              <span className="ml-1 text-xs font-normal">（默认 {defaults[key]}）</span>
            </>
          }
          className="grid-cols-[minmax(0,1fr)_11.5rem]"
        >
          <Input
            type="number"
            step={key === "task_default_limit" || key === "daily_quota" ? "1" : "any"}
            min={key === "task_default_limit" || key === "daily_quota" ? "1" : "0"}
            required
            value={values[key] ?? ""}
            onChange={(e) => setValues({ ...values, [key]: e.target.valueAsNumber })}
          />
        </FormRow>
      ))}
      {save.isError && !errorField && <Notice>{save.error.message}</Notice>}
      {reset.isError && <Notice>{reset.error.message}</Notice>}
      <div className="flex justify-end gap-2 pt-1">
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
        <Button type="submit" disabled={save.isPending || reset.isPending}>
          保存
        </Button>
      </div>
    </form>
  );
}

const outcomeTones: Record<string, StatusTone> = {
  cooldown: "warning",
  locked: "danger",
  login_required: "warning",
};

function RiskEvents() {
  const [platform, setPlatform] = useState<Platform | "">("");
  const events = useRiskEvents(platform);
  return (
    <section aria-label="风控事件" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold tracking-tight">风控事件</h3>
        <FormSelect
          aria-label="平台筛选"
          size="sm"
          className="w-32 rounded-full border-0 bg-muted shadow-none dark:bg-muted"
          value={platform}
          onValueChange={(value) => setPlatform(value as Platform | "")}
          options={[
            { value: "", label: "全部平台" },
            { value: "bili", label: "B 站" },
            { value: "xhs", label: "小红书" },
          ]}
        />
      </div>
      {events.isError && <Notice>无法加载风控事件</Notice>}
      {events.data?.length === 0 && <p className="text-muted-foreground">暂无风控事件</p>}
      {!!events.data?.length && (
        <Table className="text-[13px]">
          <TableHeader>
            <TableRow className="border-0 hover:bg-transparent">
              <TableHead className="rounded-l-lg bg-muted">时间</TableHead>
              <TableHead className="bg-muted">平台</TableHead>
              <TableHead className="bg-muted">信号</TableHead>
              <TableHead className="bg-muted">任务</TableHead>
              <TableHead className="bg-muted">结果</TableHead>
              <TableHead className="rounded-r-lg bg-muted">
                <span className="sr-only">限速参数</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.data.map((event) => (
              <TableRow key={event.id}>
                <TableCell className="tabular-nums">{formatDateTime(event.at)}</TableCell>
                <TableCell>
                  <PlatformTag platform={event.platform} />
                </TableCell>
                <TableCell className="max-w-40 truncate">{event.signal}</TableCell>
                <TableCell>
                  {event.task_id === null ? "无任务" : `任务 ${event.task_id}`}
                  <span className="block text-xs text-muted-foreground">
                    已采 {event.collected_count} 条
                  </span>
                </TableCell>
                <TableCell>
                  <StatusBadge tone={outcomeTones[event.outcome] ?? "neutral"}>
                    {event.outcome === "cooldown"
                      ? "冷却"
                      : event.outcome === "locked"
                        ? "锁定"
                        : event.outcome === "login_required"
                          ? "需要登录"
                          : event.outcome}
                  </StatusBadge>
                  {event.outcome === "cooldown" && event.outcome_until && (
                    <span className="block text-xs text-muted-foreground">
                      至 {formatDateTime(event.outcome_until)}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button type="button" variant="ghost" size="sm">
                        参数
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-80 rounded-2xl">
                      <pre className="max-h-64 overflow-auto text-xs break-all whitespace-pre-wrap">
                        {JSON.stringify(event.rate_params, null, 2)}
                      </pre>
                    </PopoverContent>
                  </Popover>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
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
      <p className="text-muted-foreground">改动只对之后开始的任务生效，单任务上限不可调。</p>
      {settings.isError && <Notice>无法加载采集设置</Notice>}
      {settings.data && (
        <>
          <CheckRow
            label="登录后预热"
            checked={settings.data.warmup_enabled}
            disabled={update.isPending}
            onCheckedChange={(warmup_enabled) => update.mutate({ warmup_enabled })}
          />
          {update.isError && <Notice>{update.error.message}</Notice>}
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
      <CheckRow
        label="风控时发系统通知"
        checked={notify}
        onCheckedChange={async (checked) => {
          if (!checked) {
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
      />
      {notifyError && <Notice>{notifyError}</Notice>}
      <RiskEvents />
    </div>
  );
}
