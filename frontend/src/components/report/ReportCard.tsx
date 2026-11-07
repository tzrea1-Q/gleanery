import { useEffect } from "react";
import { useAuiState, type ToolCallMessagePartComponent } from "@assistant-ui/react";
import type { components } from "@/api/schema";
import { ChatCard } from "@/components/common/ChatCard";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/stores/workspace";

type Args = { report_id?: number };
type Result = {
  report_id?: number;
  title?: string;
  version?: number;
  basis?: components["schemas"]["ReportBasis"] | null;
  error?: { code?: string; message?: string };
};
type Part = { type: string; toolName?: string; toolCallId?: string; result?: Result };

export const ReportCard: ToolCallMessagePartComponent<Args, Result> = ({
  toolName,
  toolCallId,
  result,
  status,
}) => {
  const latest = useAuiState((state) => {
    let last: string | undefined;
    for (const message of state.thread.messages)
      for (const part of message.content as readonly Part[]) {
        if (
          part.type === "tool-call" &&
          (part.toolName === "save_report" || part.toolName === "update_report") &&
          !part.result?.error &&
          part.result?.report_id === result?.report_id
        )
          last = part.toolCallId;
      }
    return !last || last === toolCallId;
  });
  const arrived = useWorkspace((s) => s.reportArrived);
  const open = useWorkspace((s) => s.openReport);
  const id = result?.report_id;
  const write = toolName === "save_report" || toolName === "update_report";
  const running = write && status.type === "running" && !result;
  useEffect(() => {
    if (!running) return;
    useWorkspace.getState().setWriting(true);
    return () => useWorkspace.getState().setWriting(false);
  }, [running]);
  useEffect(() => {
    if (write && id && latest && !result?.error) arrived(id);
  }, [write, id, latest, result?.error, arrived]);
  if (result?.error)
    return (
      <Notice className="my-3">
        {result.error.code === "VERSION_CONFLICT"
          ? "报告刚被修改过，Agent 会取最新版再改"
          : result.error.message || "报告操作失败"}
      </Notice>
    );
  if (!write)
    return (
      <p className="my-1 text-xs text-muted-foreground">
        {status.type === "running" ? "正在" : "已"}
        {toolName === "get_report" ? "读取报告" : "查看报告列表"}
      </p>
    );
  if (!id) return <p className="my-1 text-xs text-muted-foreground">正在撰写报告</p>;
  if (!latest)
    return (
      <p className="my-1 text-xs text-muted-foreground">
        报告「{result?.title}」已更新，最新版本见下方
      </p>
    );
  return (
    <ChatCard aria-label="报告">
      <div>
        <h3 className="text-xl font-semibold tracking-tight">{result?.title}</h3>
        <p className="text-muted-foreground">
          {result?.basis
            ? `基于 ${result.basis.contents} 条内容、${result.basis.comments} 条评论 · ${result.basis.dataset_name}`
            : "未关联数据集"}
        </p>
        {toolName === "update_report" && (
          <p className="text-muted-foreground">已更新为第 {result?.version} 版</p>
        )}
      </div>
      <Button size="sm" onClick={() => open(id)}>
        在工作区打开
      </Button>
    </ChatCard>
  );
};
