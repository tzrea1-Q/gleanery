import { useContext, useState } from "react";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { ReplyingContext } from "@/lib/replying";
import { useWorkspace } from "@/stores/workspace";

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
  if (result?.error) return <p role="alert">{result.error.message}</p>;
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
    <section
      aria-label={removing ? "移出审批" : "删除审批"}
      className="my-3 space-y-2 rounded border p-3"
    >
      {query.isError && <p role="alert">无法加载影响范围</p>}
      {query.data && (
        <>
          <h3>{query.data.dataset.name}</h3>
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
      <label>
        拒绝理由（可选）
        <input
          className="block w-full rounded border p-1"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <button disabled={!query.data} onClick={() => void respond(true)}>
        批准
      </button>{" "}
      <button onClick={() => void respond(false)}>拒绝</button>
      {failed && <p role="alert">审批回应失败，请重试</p>}
    </section>
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
  if (result?.error) return <p role="alert">{result.error.message}</p>;
  if (!result?.dataset_id) return null;
  return (
    <section className="my-3 rounded border p-3">
      <p>
        {dataset.data?.name ?? result.name}
        {dataset.data
          ? ` · ${dataset.data.total} 条`
          : result.total !== undefined
            ? ` · ${result.total} 条`
            : ""}
      </p>
      <button onClick={() => open(result.dataset_id!)}>在工作区查看</button>
    </section>
  );
};
