import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api } from "@/api/client";
import { useDatasets } from "@/api/queries-collect";
import type { components } from "@/api/schema";
import { FormRow } from "@/components/common/FormRow";
import { Notice } from "@/components/common/Notice";
import { PlatformTag } from "@/components/common/PlatformTag";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspace } from "@/stores/workspace";
import { ExportButton } from "./ExportButton";
import { formatDateTime } from "@/lib/format";

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
    <article className="flex flex-col gap-3 rounded-2xl bg-card p-5">
      <div>
        <h2 className="truncate text-lg font-semibold tracking-tight">{dataset.name}</h2>
        <p className="line-clamp-2 text-muted-foreground">{dataset.description || "暂无说明"}</p>
      </div>
      <div className="flex items-end justify-between gap-3">
        <p className="text-3xl font-semibold tracking-tight tabular-nums">
          {dataset.total}
          <span className="ml-1 text-sm font-normal text-muted-foreground">条内容</span>
        </p>
        <div className="flex flex-wrap justify-end gap-1">
          {Object.keys(dataset.counts).map((platform) => (
            <PlatformTag key={platform} platform={platform} />
          ))}
        </div>
      </div>
      <div className="space-y-0.5 text-xs text-muted-foreground">
        <p>
          {Object.entries(dataset.counts)
            .map(
              ([platform, count]) =>
                `${platform === "bili" ? "B 站" : platform === "xhs" ? "小红书" : platform} ${count} 条`,
            )
            .join("，") || "暂无平台内容"}
        </p>
        <p>
          最近追加：
          {dataset.last_appended_at === null ? "暂无" : formatDateTime(dataset.last_appended_at)}
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
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            useWorkspace.getState().openDataset(dataset.id);
            useWorkspace.getState().setWide(true);
          }}
        >
          打开
        </Button>
        <ExportButton datasetId={dataset.id} />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setName(dataset.name);
            setDescription(dataset.description);
            setError("");
            setEditing(true);
          }}
        >
          编辑
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          disabled={loadImpact.isPending}
          onClick={() => {
            setError("");
            loadImpact.mutate();
          }}
        >
          删除
        </Button>
      </div>
      {error && !editing && !impact && <Notice>{error}</Notice>}
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
            <FormRow label="名称" stacked>
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </FormRow>
            <FormRow label="说明" stacked>
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </FormRow>
            {error && <Notice>{error}</Notice>}
            <div className="flex justify-end">
              <Button type="submit" disabled={save.isPending}>
                保存
              </Button>
            </div>
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
              {error && <Notice>{error}</Notice>}
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="destructive"
                  disabled={remove.isPending}
                  onClick={() => {
                    setError("");
                    remove.mutate();
                  }}
                >
                  {impact.active_task_ids.length ? "停止这些任务并删除" : "确认删除"}
                </Button>
              </div>
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
    <div className="h-full space-y-5 overflow-y-auto px-6 py-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">所有数据集</h1>
          <p className="text-muted-foreground">
            {data ? `共 ${data.length} 个数据集` : "采集结果都在这里"}
          </p>
        </div>
        <Input
          aria-label="搜索数据集"
          placeholder="搜索数据集"
          className="w-56 rounded-full border-0 bg-card shadow-none dark:bg-card"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      {isPending ? (
        <div role="status" aria-label="正在加载数据集…" className="grid gap-3 lg:grid-cols-2">
          <Skeleton className="h-48 rounded-2xl" />
          <Skeleton className="h-48 rounded-2xl" />
        </div>
      ) : isError ? (
        <Notice>无法加载数据集</Notice>
      ) : datasets?.length ? (
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {datasets.map((dataset) => (
            <DatasetRow key={dataset.id} dataset={dataset} />
          ))}
        </div>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>没有找到数据集</EmptyTitle>
            <EmptyDescription>
              {search ? "换个关键词试试" : "在对话里让 Agent 采集一次，结果会出现在这里"}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}
