import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api } from "@/api/client";
import { useDatasets } from "@/api/queries-collect";
import type { components } from "@/api/schema";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useWorkspace } from "@/stores/workspace";
import { ExportButton } from "./ExportButton";

type Dataset = components["schemas"]["DatasetOut"];
type Impact = components["schemas"]["DeleteImpact"];

function DatasetRow({ dataset }: { dataset: Dataset }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(dataset.name);
  const [description, setDescription] = useState(dataset.description);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: async () => {
      const { response } = await api.PATCH("/api/datasets/{dataset_id}", {
        params: { path: { dataset_id: dataset.id } },
        body: { name: name.trim(), description },
      });
      if (!response.ok) throw new Error("保存失败，请重试");
    },
    onSuccess: async () => {
      setEditing(false);
      await client.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: () => setError("保存失败，请重试"),
  });
  const loadImpact = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.GET("/api/datasets/{dataset_id}/delete-impact", {
        params: { path: { dataset_id: dataset.id } },
      });
      if (!response.ok || !data) throw new Error("无法获取删除影响，请重试");
      return data;
    },
    onSuccess: setImpact,
    onError: () => setError("无法获取删除影响，请重试"),
  });
  const remove = useMutation({
    mutationFn: async () => {
      const { response } = await api.DELETE("/api/datasets/{dataset_id}", {
        params: {
          path: { dataset_id: dataset.id },
          query: { stop_active: !!impact?.active_task_ids.length },
        },
      });
      if (!response.ok) throw new Error("删除失败，请重新查看删除影响后重试");
    },
    onSuccess: async () => {
      setImpact(null);
      if (useWorkspace.getState().datasetId === dataset.id)
        useWorkspace.getState().openDataset(null);
      await client.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: () => setError("删除失败，请重新查看删除影响后重试"),
  });
  return (
    <article className="space-y-2 rounded border p-4">
      <h2 className="font-semibold">{dataset.name}</h2>
      <p>{dataset.description || "暂无说明"}</p>
      <p>
        {Object.entries(dataset.counts)
          .map(
            ([platform, count]) =>
              `${platform === "bili" ? "B 站" : platform === "xhs" ? "小红书" : platform} ${count} 条`,
          )
          .join("，") || "暂无平台内容"}
        ；共 {dataset.total} 条
      </p>
      <p>
        最近追加：
        {dataset.last_appended_at === null
          ? "暂无"
          : new Date(dataset.last_appended_at).toLocaleString()}
      </p>
      <p>
        来源对话：
        {dataset.created_in_conversation_id === null ? (
          "无"
        ) : (
          <Link
            className="underline"
            to="/c/$conversationId"
            params={{ conversationId: String(dataset.created_in_conversation_id) }}
          >
            对话 {dataset.created_in_conversation_id}
          </Link>
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded border p-1"
          onClick={() => {
            useWorkspace.getState().openDataset(dataset.id);
            useWorkspace.getState().setWide(true);
          }}
        >
          打开
        </button>
        <button
          type="button"
          className="rounded border p-1"
          onClick={() => {
            setName(dataset.name);
            setDescription(dataset.description);
            setError("");
            setEditing(true);
          }}
        >
          编辑
        </button>
        <ExportButton datasetId={dataset.id} />
        <button
          type="button"
          className="rounded border p-1"
          disabled={loadImpact.isPending}
          onClick={() => {
            setError("");
            loadImpact.mutate();
          }}
        >
          删除
        </button>
      </div>
      {error && !editing && !impact && <p role="alert">{error}</p>}
      <Dialog
        open={editing}
        onOpenChange={(open) => {
          if (!save.isPending) setEditing(open);
        }}
      >
        <DialogContent>
          <DialogTitle>编辑数据集</DialogTitle>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) {
                setError("名称不能为空");
                return;
              }
              setError("");
              save.mutate();
            }}
          >
            <label className="block">
              名称
              <input
                className="block w-full rounded border p-1"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="block">
              说明
              <textarea
                className="block w-full rounded border p-1"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            {error && <p role="alert">{error}</p>}
            <button type="submit" className="rounded border p-1" disabled={save.isPending}>
              保存
            </button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={impact !== null}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) {
            setImpact(null);
            setError("");
          }
        }}
      >
        <DialogContent>
          <DialogTitle>删除数据集：{dataset.name}</DialogTitle>
          {impact && (
            <>
              <p>
                将删除 {impact.contents} 条内容的成员关系、{impact.tasks} 个采集任务；其中{" "}
                {impact.recycled_contents} 条内容、{impact.recycled_comments}{" "}
                条评论不在其他数据集里，会从内容库删除；删除后无法恢复。
              </p>
              {impact.reports > 0 && (
                <p>
                  {impact.reports}{" "}
                  份报告以它为主数据集，删除后报告保留，被回收内容的引用改显示快照。
                </p>
              )}
              {impact.active_task_ids.length > 0 && (
                <p>有采集任务还没结束：{impact.active_task_ids.join("、")}</p>
              )}
              {error && <p role="alert">{error}</p>}
              <button
                type="button"
                className="rounded border p-1"
                disabled={remove.isPending}
                onClick={() => {
                  setError("");
                  remove.mutate();
                }}
              >
                {impact.active_task_ids.length ? "停止这些任务并删除" : "确认删除"}
              </button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </article>
  );
}

export function DatasetList() {
  const { data, isPending, isError } = useDatasets();
  const [search, setSearch] = useState("");
  const datasets = data?.filter((dataset) =>
    dataset.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  return (
    <div className="h-full space-y-4 overflow-y-auto p-6">
      <h1 className="text-xl font-semibold">所有数据集</h1>
      <label>
        搜索数据集
        <input
          className="ml-2 rounded border p-1"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {isPending ? (
        <p>正在加载数据集…</p>
      ) : isError ? (
        <p role="alert">无法加载数据集</p>
      ) : datasets?.length ? (
        datasets.map((dataset) => <DatasetRow key={dataset.id} dataset={dataset} />)
      ) : (
        <p>没有找到数据集</p>
      )}
    </div>
  );
}
