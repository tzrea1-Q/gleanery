import type { components } from "@/api/schema";
import { duration } from "./Progress";
type Plan = components["schemas"]["PlanOut"];
export function PlanSummary({ plan }: { plan: Plan }) {
  return (
    <div className="space-y-2 text-sm">
      <h3 className="font-semibold">
        {plan.body.title} · {plan.status === "draft" ? "草稿" : "已确认"}
      </h3>
      {plan.body.sections.map((s, i) => (
        <div key={i}>
          <p>
            {s.platform === "bili" ? "B 站" : "小红书"} · 关键词：{s.keywords?.join("、") || "无"} ·
            指定内容：{s.targets?.join("、") || "无"}
          </p>
          <p>
            数量 {s.quantity} · 排序 {{ default: "默认", hot: "热度", new: "最新" }[s.sort]} ·
            时间范围{" "}
            {s.time_range?.last_days
              ? `近 ${s.time_range.last_days} 天`
              : s.time_range
                ? `${s.time_range.start ?? "不限"} 至 ${s.time_range.end ?? "不限"}`
                : "不限"}
          </p>
          <p>
            深度：{s.depth.detail ? "详情" : "摘要"}，评论 {s.depth.comments}，二级评论{" "}
            {s.depth.sub_comments ? `每条 ${s.depth.sub_comments_per_root}` : "不采集"}
            {s.platform === "bili" && `，字幕 ${s.depth.subtitles ? "采集" : "不采集"}`} · 预计{" "}
            {duration(plan.estimate_seconds[s.platform] ?? 0)}
          </p>
        </div>
      ))}
      {(["error", "warning"] as const).map(
        (severity) =>
          plan.issues.some((x) => x.severity === severity) && (
            <div key={severity}>
              <b>{severity === "error" ? "错误" : "提示"}：</b>
              {plan.issues
                .filter((x) => x.severity === severity)
                .map((x, i) => (
                  <p key={i}>
                    {x.message}
                    {x.code === "QUOTA_EXCEEDED" && "（超出部分明天继续）"}
                  </p>
                ))}
            </div>
          ),
      )}
    </div>
  );
}
