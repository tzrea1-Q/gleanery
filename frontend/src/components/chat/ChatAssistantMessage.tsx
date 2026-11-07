import {
  ActionBarPrimitive,
  MessagePrimitive,
  useAui,
  useAuiState,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";
import { PlanCard, StartCard, DatasetsCard } from "@/components/collect/ToolCards";
import { ModelErrorCard } from "@/components/model/ModelErrorCard";
import {
  DatasetSavedCard,
  DeleteApprovalCard,
  RemoveApprovalCard,
} from "@/components/dataset/ApprovalCards";
import { ExportCard } from "@/components/dataset/ExportCard";
import { ReportCard } from "@/components/report/ReportCard";

/** 没有专门卡片的工具，在对话里只留一行步骤说明。 */
const STEP_LABELS: Record<string, string> = {
  query_contents: "查询内容",
  get_content: "读取内容详情",
  query_comments: "查询评论",
  aggregate: "统计汇总",
  count_mentions: "统计提及次数",
  run_sql: "执行 SQL 查询",
  get_collection_status: "查看采集进度",
  stop_collection: "停止采集",
  get_platform_status: "查看平台状态",
};

const ToolStep: ToolCallMessagePartComponent = ({ toolName, status }) => (
  <p className="my-1 text-xs text-muted-foreground">
    {status.type === "running" ? "正在" : "已"}
    {STEP_LABELS[toolName] ?? toolName}
  </p>
);

/** 回复进行中、但还没有文字在出时（模型思考、等工具结果），给一个明确的进行中提示。 */
function RunningHint() {
  const hint = useAuiState((s) => {
    if (s.message.status?.type !== "running") return null;
    const last = s.message.parts.at(-1);
    if (last?.type === "text" && last.text) return null;
    if (last?.type === "tool-call" && last.result === undefined)
      return `正在${STEP_LABELS[last.toolName] ?? "调用工具"}…`;
    return "思考中…";
  });
  if (!hint) return null;
  return (
    <p
      role="status"
      aria-label="回复进度"
      className="my-2 animate-pulse text-sm text-muted-foreground"
    >
      {hint}
    </p>
  );
}

export function ChatAssistantMessage() {
  const status = useAuiState((s) => s.message.status);
  const hasText = useAuiState((s) =>
    s.message.parts.some((part) => part.type === "text" && !!part.text),
  );
  const aui = useAui();
  return (
    <MessagePrimitive.Root className="px-2">
      <MessagePrimitive.Parts
        components={{
          Text: MarkdownText,
          tools: {
            by_name: {
              propose_collection_plan: PlanCard,
              update_collection_plan: PlanCard,
              get_collection_plan: PlanCard,
              start_collection: StartCard,
              list_datasets: DatasetsCard,
              save_as_dataset: DatasetSavedCard,
              update_dataset: DatasetSavedCard,
              remove_from_dataset: RemoveApprovalCard,
              delete_dataset: DeleteApprovalCard,
              export_dataset: ExportCard,
              save_report: ReportCard,
              update_report: ReportCard,
              get_report: ReportCard,
              list_reports: ReportCard,
            },
            Fallback: ToolStep,
          },
        }}
      />
      <RunningHint />
      {status?.type === "incomplete" && status.reason === "error" && hasText && (
        <p className="text-sm text-muted-foreground">未完成</p>
      )}
      <ActionBarPrimitive.Root hideWhenRunning>
        <ActionBarPrimitive.Copy className="rounded border p-1">复制</ActionBarPrimitive.Copy>
        <ActionBarPrimitive.Reload className="rounded border p-1">
          重新生成
        </ActionBarPrimitive.Reload>
      </ActionBarPrimitive.Root>
      {status?.type === "incomplete" && status.reason === "error" && (
        <ModelErrorCard error={status.error} reload={() => aui.message.reload()} />
      )}
    </MessagePrimitive.Root>
  );
}
