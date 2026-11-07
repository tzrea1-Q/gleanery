import { Check } from "lucide-react";
import type { ReactNode } from "react";
import type { components } from "@/api/schema";
import { Notice } from "@/components/common/Notice";
import { PlatformTag } from "@/components/common/PlatformTag";
import { StatusBadge } from "@/components/common/StatusBadge";
import { duration } from "./Progress";
type Plan = components["schemas"]["PlanOut"];
type Section = Plan["body"]["sections"][number];

const sortNames = { default: "默认", hot: "热度", new: "最新" };

function timeRange(s: Section) {
  if (s.time_range?.last_days) return `近 ${s.time_range.last_days} 天`;
  if (s.time_range) return `${s.time_range.start ?? "不限"} 至 ${s.time_range.end ?? "不限"}`;
  return "不限";
}

function depth(s: Section) {
  const replies = s.depth.sub_comments ? `，二级评论每条 ${s.depth.sub_comments_per_root}` : "";
  const subtitles = s.platform === "bili" && s.depth.subtitles ? "，字幕" : "";
  return `${s.depth.detail ? "详情" : "摘要"}，评论 ${s.depth.comments}${replies}${subtitles}`;
}

function CheckItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b py-2 last:border-b-0">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-lime text-[#16161a]">
        <Check aria-hidden className="size-3" strokeWidth={3} />
      </span>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="ml-auto min-w-0 text-right font-medium">{children}</dd>
    </div>
  );
}

/** 审批时逐项核对用。平时看的摘要是 `PlanSummary`。 */
export function PlanChecklist({ plan }: { plan: Plan }) {
  return (
    <div className="space-y-3">
      {plan.body.sections.map((s, i) => (
        <div key={i}>
          <PlatformTag platform={s.platform} />
          <dl className="mt-1">
            {!!s.keywords?.length && <CheckItem label="关键词">{s.keywords.join("、")}</CheckItem>}
            {!!s.targets?.length && <CheckItem label="指定内容">{s.targets.join("、")}</CheckItem>}
            <CheckItem label="数量">
              {s.quantity} 条 · {sortNames[s.sort]}排序
            </CheckItem>
            <CheckItem label="时间范围">{timeRange(s)}</CheckItem>
            <CheckItem label="采集深度">{depth(s)}</CheckItem>
            <CheckItem label="预计用时">
              {duration(plan.estimate_seconds[s.platform] ?? 0)}
            </CheckItem>
          </dl>
        </div>
      ))}
      <PlanIssues plan={plan} />
    </div>
  );
}

function PlanIssues({ plan }: { plan: Plan }) {
  return (["error", "warning"] as const).map(
    (severity) =>
      plan.issues.some((x) => x.severity === severity) && (
        <Notice key={severity} tone={severity === "error" ? "error" : "warning"}>
          <b>{severity === "error" ? "错误" : "提示"}：</b>
          {plan.issues
            .filter((x) => x.severity === severity)
            .map((x, i) => (
              <p key={i}>
                {x.message}
                {x.code === "QUOTA_EXCEEDED" && "（超出部分明天继续）"}
              </p>
            ))}
        </Notice>
      ),
  );
}

export function PlanSummary({ plan }: { plan: Plan }) {
  return (
    <div className="space-y-2">
      <h3
        aria-label={`${plan.body.title} · ${plan.status === "draft" ? "草稿" : "已确认"}`}
        className="flex items-center gap-2 font-semibold"
      >
        <span className="min-w-0 truncate">{plan.body.title}</span>
        <StatusBadge tone={plan.status === "draft" ? "info" : "success"}>
          {plan.status === "draft" ? "草稿" : "已确认"}
        </StatusBadge>
      </h3>
      {plan.body.sections.map((s, i) => (
        <div key={i} className="space-y-0.5 text-muted-foreground">
          <p className="flex flex-wrap items-center gap-x-2 text-foreground">
            <PlatformTag platform={s.platform} />
            <span>
              关键词：{s.keywords?.join("、") || "无"} · 指定内容：{s.targets?.join("、") || "无"}
            </span>
          </p>
          <p>
            数量 {s.quantity} · 排序 {sortNames[s.sort]} · 时间范围 {timeRange(s)}
          </p>
          <p>
            深度：{s.depth.detail ? "详情" : "摘要"}，评论 {s.depth.comments}，二级评论{" "}
            {s.depth.sub_comments ? `每条 ${s.depth.sub_comments_per_root}` : "不采集"}
            {s.platform === "bili" && `，字幕 ${s.depth.subtitles ? "采集" : "不采集"}`} · 预计{" "}
            {duration(plan.estimate_seconds[s.platform] ?? 0)}
          </p>
        </div>
      ))}
      <PlanIssues plan={plan} />
    </div>
  );
}
