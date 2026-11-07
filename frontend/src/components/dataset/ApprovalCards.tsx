import { useContext, useState } from "react";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { ReplyingContext } from "@/lib/replying";
import { useWorkspace } from "@/stores/workspace";
import { ChatCard } from "@/components/common/ChatCard";
import { FormRow } from "@/components/common/FormRow";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Args = { dataset_id?: number; content_ids?: number[] };
type Result = { dataset_id?: number; name?: string; total?: number; error?: { message?: string } };

const ApprovalCard: ToolCallMessagePartComponent<Args, Result> = ({
  args,
  result,
  approval,
  respondToApproval,
  toolName,
}) => {
  const [reason, setReason] = useState("");
  const [failed, setFailed] = useState(false);
  const id = args.dataset_id;
  const removing = toolName === "remove_from_dataset";
  const pending = !!approval && approval.approved === undefined && !approval.resolution;
  const replying = useContext(ReplyingContext);
  const query = useQuery({
    queryKey: ["dataset-approval", id, removing, args.content_ids],
    enabled: !!id && pending,
    queryFn: async () => {
      const dataset = await api.GET("/api/datasets/{dataset_id}", {
        params: { path: { dataset_id: id! } },
      });
      if (!dataset.data) throw new Error();
      if (removing) {
        const impact = await api.POST("/api/datasets/{dataset_id}/remove-impact", {
          params: { path: { dataset_id: id! } },
          body: { content_ids: args.content_ids ?? [] },
        });
        if (!impact.data) throw new Error();
        const titles = await Promise.all(
          (args.content_ids ?? []).slice(0, 10).map(async (content_id) => {
            const content = await api.GET("/api/contents/{content_id}", {
              params: { path: { content_id } },
            });
            return content.data?.title ?? `内容 ${content_id}`;
          }),
        );
        return { dataset: dataset.data, impact: impact.data, titles };
      }
      const impact = await api.GET("/api/datasets/{dataset_id}/delete-impact", {
        params: { path: { dataset_id: id! } },
      });
      if (!impact.data) throw new Error();
      return { dataset: dataset.data, impact: impact.data, titles: [] };
    },
  });
  if (approval?.approved === false)
    return <p>已拒绝{approval.reason ? `：${approval.reason}` : ""}</p>;
  if (result?.error) return <Notice>{result.error.message}</Notice>;
  if (!pending) return result ? <p>{removing ? "已移出" : "已删除"}</p> : null;
  if (replying) return <p role="status">Agent 正在处理…</p>;
  const respond = async (approved: boolean) => {
    try {
      setFailed(false);
      await respondToApproval({ approved, reason: approved ? undefined : reason });
    } catch {
      setFailed(true);
    }
  };
  return (
    <ChatCard aria-label={removing ? "移出审批" : "删除审批"}>
      {query.isError && <Notice>无法加载影响范围</Notice>}
      {query.data && (
        <>
          <h3 className="text-xl font-semibold tracking-tight">{query.data.dataset.name}</h3>
          {"removed" in query.data.impact && (
            <>
              <p>移出 {query.data.impact.removed} 条</p>
              <ul>
                {query.data.titles.map((title, i) => (
                  <li key={i}>{title}</li>
                ))}
              </ul>
            </>
          )}
          <p>
            {"removed" in query.data.impact
              ? ""
              : `将删除 ${query.data.impact.contents} 条内容的成员关系、${query.data.impact.tasks} 个采集任务；`}
            {query.data.impact.recycled_contents
              ? `其中 ${query.data.impact.recycled_contents} 条内容、${query.data.impact.recycled_comments} 条评论不在其他数据集里，会从内容库删除`
              : "这些内容都还在其他数据集里，不会从内容库删除"}
            {"removed" in query.data.impact ? "。" : "；删除后无法恢复。"}
          </p>
          {"reports" in query.data.impact && query.data.impact.reports > 0 && (
            <p>
              {query.data.impact.reports}{" "}
              份报告以它为主数据集，删除后报告保留，被回收内容的引用改显示快照。
            </p>
          )}
        </>
      )}
      <FormRow label="拒绝理由（可选）" stacked>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} />
      </FormRow>
      <div className="flex gap-2">
        <Button variant="destructive" disabled={!query.data} onClick={() => void respond(true)}>
          批准
        </Button>
        <Button variant="outline" onClick={() => void respond(false)}>
          拒绝
        </Button>
      </div>
      {failed && <Notice>审批回应失败，请重试</Notice>}
    </ChatCard>
  );
};
export const RemoveApprovalCard = ApprovalCard;
export const DeleteApprovalCard = ApprovalCard;
export const DatasetSavedCard: ToolCallMessagePartComponent<Args, Result> = ({ result }) => {
  const open = useWorkspace((s) => s.openDataset);
  const dataset = useQuery({
    queryKey: ["dataset", result?.dataset_id],
    enabled: !!result?.dataset_id,
    queryFn: async () => {
      const { data } = await api.GET("/api/datasets/{dataset_id}", {
        params: { path: { dataset_id: result!.dataset_id! } },
      });
      if (!data) throw new Error();
      return data;
    },
  });
  if (result?.error) return <Notice className="my-3">{result.error.message}</Notice>;
  if (!result?.dataset_id) return null;
  return (
    <ChatCard className="flex items-center justify-between gap-3 space-y-0">
      <p>
        {dataset.data?.name ?? result.name}
        {dataset.data
          ? ` · ${dataset.data.total} 条`
          : result.total !== undefined
            ? ` · ${result.total} 条`
            : ""}
      </p>
      <Button variant="outline" size="sm" onClick={() => open(result.dataset_id!)}>
        在工作区查看
      </Button>
    </ChatCard>
  );
};
