import { useContext, useEffect, useRef, useState } from "react";
import { useAui, useAuiState, type ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useDatasets, usePlan, useTasks } from "@/api/queries-collect";
import { ReplyingContext } from "@/lib/replying";
import { useWorkspace } from "@/stores/workspace";
import { DatasetTable } from "@/components/dataset/DatasetTable";
import { PlanSummary } from "./PlanSummary";
import { finished, Progress } from "./Progress";

type Args = { plan_id?: number };
type Result = {
  plan_id?: number;
  dataset_id?: number;
  error?: { code?: string; message?: string };
};
const PLAN_TOOLS = new Set([
  "propose_collection_plan",
  "update_collection_plan",
  "get_collection_plan",
]);
type ToolPart = {
  type: string;
  toolName?: string;
  toolCallId?: string;
  args?: Args;
  result?: Result;
};

// 同一份计划在对话里被起草、读取、修改多次时，只有最后一张卡片展开，前面的收成一行，
// 免得几张一模一样的最新版本摞在一起（2026-11-02 冒烟反馈）。
function useIsLatestPlanCard(planId: number | undefined, toolCallId: string) {
  return useAuiState((s) => {
    let last: string | undefined;
    for (const message of s.thread.messages)
      for (const part of message.content as readonly ToolPart[]) {
        if (part.type !== "tool-call" || !part.toolName || !PLAN_TOOLS.has(part.toolName)) continue;
        if (part.result?.error) continue;
        if ((part.result?.plan_id ?? part.args?.plan_id) === planId) last = part.toolCallId;
      }
    return last === undefined || last === toolCallId;
  });
}

export const PlanCard: ToolCallMessagePartComponent<Args, Result> = ({
  args,
  result,
  toolCallId,
}) => {
  const id = result?.plan_id ?? args.plan_id;
  const plan = usePlan(id);
  const latest = useIsLatestPlanCard(id, toolCallId);
  const select = useWorkspace((s) => s.select);
  // 版本冲突由 Agent 自己重读后再改，用户不用看到。
  if (result?.error?.code === "VERSION_CONFLICT") return null;
  if (result?.error) return <p role="alert">{result.error.message}</p>;
  if (!plan.data) return plan.isError ? <p role="alert">无法加载计划</p> : null;
  if (!latest)
    return (
      <p className="my-2 text-sm text-muted-foreground">
        计划「{plan.data.body.title}」已更新，最新版本见下方
      </p>
    );
  return (
    <section aria-label="计划摘要" className="my-3 space-y-2 rounded border p-3">
      <PlanSummary plan={plan.data} />
      <button className="rounded border p-1" onClick={() => select("plan")}>
        在工作区编辑
      </button>
    </section>
  );
};
export const StartCard: ToolCallMessagePartComponent<Args, Result> = ({
  args,
  result,
  approval,
  respondToApproval,
}) => {
  const id = result?.plan_id ?? args.plan_id;
  const plan = usePlan(id);
  const tasks = useTasks({ plan_id: id });
  const register = useWorkspace((s) => s.register);
  const [reason, setReason] = useState("");
  const [error, setError] = useState(false);
  const aui = useAui();
  const respondRef = useRef(respondToApproval);
  useEffect(() => {
    respondRef.current = respondToApproval;
  }, [respondToApproval]);
  const pending = !!approval && approval.approved === undefined && !approval.resolution;
  const replying = useContext(ReplyingContext);
  useEffect(() => {
    if (!id || !pending) return;
    const fn = async (approved: boolean, why?: string) => {
      try {
        setError(false);
        await respondRef.current({ approved, reason: why });
      } catch {
        setError(true);
      }
    };
    register(id, fn);
    return () => register(id, undefined);
  }, [id, pending, register]);
  if (approval?.approved === false)
    return <p>已拒绝采集{approval.reason ? `：${approval.reason}` : ""}</p>;
  if (result?.error) return <p role="alert">{result.error.message}</p>;
  if (!id) return null;
  if (pending && replying) return <p role="status">Agent 正在处理…</p>;
  if (pending)
    return (
      <section aria-label="采集审批" className="my-3 space-y-2 rounded border p-3">
        <h3 className="font-semibold">确认开始采集</h3>
        {plan.data && <PlanSummary plan={plan.data} />}
        <label>
          拒绝理由（可选）
          <input
            className="block w-full rounded border p-1"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <div className="flex gap-2">
          <button
            className="rounded border p-1"
            onClick={() => void useWorkspace.getState().approvals[id]?.(true)}
          >
            批准
          </button>
          <button
            className="rounded border p-1"
            onClick={() => void useWorkspace.getState().approvals[id]?.(false, reason)}
          >
            拒绝
          </button>
        </div>
        {error && <p role="alert">审批回应失败，请重试</p>}
      </section>
    );
  if (!result || !tasks.data?.length) return null;
  const done = tasks.data.every(finished);
  const allComplete = tasks.data.every((t) => t.status === "completed");
  const datasetId = tasks.data[0].dataset_id;
  return (
    <section
      aria-label={done ? "采集结束" : "采集进度"}
      className="my-3 space-y-2 rounded border p-3"
    >
      <h3 className="font-semibold">{done ? "采集结束" : "采集进度"}</h3>
      <Progress tasks={tasks.data} />
      {done && allComplete && (
        <>
          <DatasetTable id={datasetId} preview />
          <button
            className="rounded border p-1"
            onClick={() => useWorkspace.getState().openDataset(datasetId)}
          >
            在工作区查看
          </button>
        </>
      )}
      {done && !allComplete && (
        <div className="flex gap-2">
          {["用已有数据继续整理", "补采"].map((text) => (
            <button
              key={text}
              className="rounded border p-1"
              onClick={() => aui.thread.composer().setText(text)}
            >
              {text}
            </button>
          ))}
        </div>
      )}
    </section>
  );
};
export const DatasetsCard: ToolCallMessagePartComponent<Args, Result> = ({ result }) => {
  const datasets = useDatasets();
  if (result?.error) return <p role="alert">{result.error.message}</p>;
  return (
    <section aria-label="数据集列表" className="my-3 rounded border p-3">
      <h3>数据集</h3>
      {datasets.data?.map((d) => (
        <p key={d.id}>
          {d.name} · {d.total} 条
        </p>
      ))}
      {datasets.isError && <p role="alert">无法加载数据集</p>}
    </section>
  );
};
