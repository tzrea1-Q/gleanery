import { useEffect, useRef, useState } from "react";
import { Check, TriangleAlert, X } from "lucide-react";
import { api } from "@/api/client";
import { useRouterState } from "@tanstack/react-router";
import { useReports } from "@/api/queries-report";
import { usePlans, useTasks } from "@/api/queries-collect";
import { Progress } from "@/components/collect/Progress";
import { DatasetTable } from "@/components/dataset/DatasetTable";
import { ReportView } from "@/components/report/ReportView";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/stores/workspace";
import { PlanEditor } from "./PlanEditor";

const stages = [
  ["plan", "计划"],
  ["collect", "采集"],
  ["dataset", "数据集"],
  ["report", "报告"],
] as const;

type StageTone = "idle" | "active" | "done" | "attention";
const stageTones: Record<StageTone, string> = {
  idle: "bg-muted text-muted-foreground",
  active: "bg-brand-muted text-brand",
  done: "bg-success-muted text-success",
  attention: "bg-attention-muted text-attention",
};

function WorkspaceEmpty({ children }: { children?: React.ReactNode }) {
  return (
    <Empty className="flex-1">
      <EmptyHeader>
        <EmptyTitle>工作区</EmptyTitle>
        <EmptyDescription>
          {children ?? "Agent 产出的计划、进度、数据集和报告会出现在这里"}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

function WorkspaceContent({ id }: { id: number }) {
  const plans = usePlans(id);
  const reports = useReports({ conversation_id: id, limit: 1 });
  const tasks = useTasks({ conversation_id: id });
  const plan = plans.data?.at(-1);
  const tab = useWorkspace((s) => s.tab);
  const notices = useWorkspace((s) => s.notices);
  const selectedDatasetId = useWorkspace((s) => s.datasetId);
  const selectedReportId = useWorkspace((s) => s.reportId);
  const select = useWorkspace((s) => s.select);
  const auto = useWorkspace((s) => s.auto);
  const previous = useRef({ plan: 0, confirmed: false, complete: false });
  const currentTasks = tasks.data?.filter((t) => t.plan_id === plan?.id) ?? [];
  const complete = currentTasks.length > 0 && currentTasks.every((t) => t.status === "completed");
  useEffect(() => {
    if (!plan || useWorkspace.getState().pendingFocus) return;
    const prev = previous.current;
    if (prev.plan !== plan.id) {
      auto("plan");
      previous.current = { plan: plan.id, confirmed: false, complete: false };
    } else if (plan.status === "confirmed" && !prev.confirmed) auto("collect");
    if (complete && !prev.complete) auto("dataset");
    previous.current = { plan: plan.id, confirmed: plan.status === "confirmed", complete };
  }, [plan, complete, auto]);
  if (id && plans.isPending && !selectedDatasetId && !selectedReportId)
    return <p className="p-4 text-muted-foreground">正在加载工作区…</p>;
  if ((plans.isError || tasks.isError) && !selectedDatasetId && !selectedReportId)
    return <Notice className="m-4 w-auto">无法加载工作区</Notice>;
  if (
    !plan &&
    !selectedDatasetId &&
    !selectedReportId &&
    !reports.data?.items.length &&
    tab !== "report"
  )
    return <WorkspaceEmpty />;
  const datasetId =
    selectedDatasetId ?? currentTasks[0]?.dataset_id ?? plan?.body.target_dataset_id;
  const collected = currentTasks.reduce((sum, t) => sum + t.progress.processed, 0);
  const planned = currentTasks.reduce((sum, t) => sum + t.progress.planned, 0);
  const paused = currentTasks.some((t) => t.status === "paused" || t.status === "failed");
  const reportCount = reports.data?.items.length ?? 0;
  const stageStates: Record<(typeof stages)[number][0], { tone: StageTone; text: string }> = {
    plan: !plan
      ? { tone: "idle", text: "未开始" }
      : plan.status === "draft"
        ? { tone: "active", text: "待确认" }
        : { tone: "done", text: "已确认" },
    collect: !currentTasks.length
      ? { tone: "idle", text: "未开始" }
      : paused
        ? { tone: "attention", text: "已暂停" }
        : complete
          ? { tone: "done", text: `${collected} / ${planned}` }
          : { tone: "active", text: `${collected} / ${planned}` },
    dataset: datasetId
      ? { tone: complete ? "done" : "active", text: collected ? `${collected} 条` : "已打开" }
      : { tone: "idle", text: "暂无" },
    report: reportCount
      ? { tone: "done", text: `${reportCount} 份` }
      : { tone: "idle", text: "未生成" },
  };
  return (
    <>
      <header className="shrink-0 p-3 pr-12">
        <nav aria-label="工作区阶段" className="grid min-w-0 grid-cols-4 gap-1.5">
          {stages.map(([key, label]) => {
            const stage = stageStates[key];
            const Icon =
              stage.tone === "done" ? Check : stage.tone === "attention" ? TriangleAlert : null;
            return (
              <Button
                key={key}
                variant={null}
                size={null}
                aria-current={tab === key ? "page" : undefined}
                className={cn(
                  "block h-auto min-w-0 rounded-xl px-2.5 py-1.5 text-left font-normal whitespace-normal aria-[current=page]:ring-2 aria-[current=page]:ring-foreground",
                  stageTones[stage.tone],
                )}
                onClick={() => select(key)}
              >
                <span className="flex items-center gap-1 text-xs font-semibold">
                  {Icon && <Icon aria-hidden className="size-3 shrink-0" />}
                  <span className="truncate">{label}</span>
                  {notices.includes(key) && (
                    <>
                      <span
                        aria-hidden
                        className="ml-auto size-1.5 shrink-0 rounded-full bg-brand"
                      />
                      <span className="sr-only">有更新</span>
                    </>
                  )}
                </span>
                <span className="block truncate text-[11px] leading-4 opacity-80">
                  {stage.text}
                </span>
              </Button>
            );
          })}
        </nav>
      </header>
      <div className="min-h-0 flex-1 overflow-auto px-4">
        {/* 底部留白放在内层：Chromium 算吸底位置时会扣掉滚动容器的 padding，操作栏下面会漏出内容。 */}
        <div className="flex min-h-full flex-col pb-4">
          {tab === "plan" && plan && <PlanEditor key={plan.id} plan={plan} />}
          {tab === "collect" &&
            (tasks.data?.length ? (
              <Progress tasks={tasks.data} />
            ) : (
              <p className="text-muted-foreground">暂无采集任务</p>
            ))}
          {tab === "dataset" &&
            (datasetId ? (
              <DatasetTable key={datasetId} id={datasetId} />
            ) : (
              <p className="text-muted-foreground">暂无数据集</p>
            ))}
          {tab === "report" && <ReportView conversationId={id} />}
        </div>
      </div>
    </>
  );
}
export function Workspace({ className }: { className?: string }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const id = Number(/^\/c\/(\d+)$/.exec(path)?.[1]);
  const previousConversation = useRef(id);
  const selected = useWorkspace((s) => s.datasetId);
  const selectedReport = useWorkspace((s) => s.reportId);
  const pending = useWorkspace((s) => s.pendingFocus);
  const [focusError, setFocusError] = useState("");
  useEffect(() => {
    if (previousConversation.current && previousConversation.current !== id && id) {
      useWorkspace.getState().openDataset(null);
      useWorkspace.getState().openReport(null);
    }
    if (id) previousConversation.current = id;
  }, [id]);
  useEffect(() => {
    if (!pending || selected) return;
    void api
      .GET("/api/locate", {
        params: {
          query: pending.commentId
            ? { comment_id: pending.commentId }
            : { content_id: pending.contentId },
        },
      })
      .then(({ data }) => {
        if (useWorkspace.getState().pendingFocus !== pending) return;
        if (data?.dataset_id) {
          setFocusError("");
          useWorkspace.getState().openDataset(data.dataset_id);
        } else {
          setFocusError(data ? "这条内容已不在任何数据集里" : "无法定位，请检查 ID 后重试");
          useWorkspace.getState().clearFocus();
        }
      })
      .catch(() => {
        if (useWorkspace.getState().pendingFocus === pending) {
          setFocusError("无法定位，请检查 ID 后重试");
          useWorkspace.getState().clearFocus();
        }
      });
  }, [pending, selected]);
  return (
    <aside
      aria-label="工作区"
      className={cn(
        "relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-3xl bg-card",
        className,
      )}
    >
      <h2 className="sr-only">工作区</h2>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="关闭工作区"
        className="absolute top-5 right-2 z-10"
        onClick={() => {
          // 列表页的工作区由所选内容决定，清空就收起；留下 closed 会让之后的对话也打不开工作区。
          if (path === "/datasets" || path === "/reports") {
            useWorkspace.getState().openDataset(null);
            useWorkspace.getState().openReport(null);
          } else useWorkspace.getState().setClosed(true);
        }}
      >
        <X />
      </Button>
      {focusError && <Notice className="m-3 mr-12 mb-0 w-auto">{focusError}</Notice>}
      {id || selected || selectedReport ? (
        <WorkspaceContent key={id || "datasets"} id={id || 0} />
      ) : (
        <WorkspaceEmpty>需求 › 计划 › 采集 › 数据集 › 报告</WorkspaceEmpty>
      )}
    </aside>
  );
}
