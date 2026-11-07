import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal } from "lucide-react";
import { api } from "@/api/client";
import {
  useReport,
  useReportActions,
  useReportRevision,
  useReportRevisions,
  useReports,
} from "@/api/queries-report";
import type { components } from "@/api/schema";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useComposer } from "@/stores/composer";
import { useWorkspace } from "@/stores/workspace";
import { ReportMarkdown } from "./ReportMarkdown";
import { ReportExportMenu } from "./ReportExportMenu";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { askConfirm } from "@/stores/confirm";

type Report = components["schemas"]["ReportDetail"];

export function ReportView({ conversationId }: { conversationId: number }) {
  const [syncError, setSyncError] = useState(false);
  const selected = useWorkspace((s) => s.reportId);
  const reports = useReports({ conversation_id: conversationId });
  const id = selected ?? reports.data?.items[0]?.id ?? null;
  const report = useReport(id);
  const writing = useWorkspace((s) => s.writing);
  useEffect(() => {
    if (!conversationId || (selected === null && !reports.data)) return;
    const controller = new AbortController();
    void api
      .PUT("/api/conversations/{conversation_id}/workspace", {
        params: { path: { conversation_id: conversationId } },
        body: { report_id: id },
        signal: controller.signal,
      })
      .then(({ response }) => {
        if (!controller.signal.aborted) setSyncError(!response.ok);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSyncError(true);
      });
    return () => controller.abort();
  }, [conversationId, id, selected, reports.data]);
  const switcher = (
    <FormSelect
      aria-label="报告"
      className="w-full rounded-full border-0 bg-muted shadow-none dark:bg-muted"
      size="sm"
      value={id ? String(id) : ""}
      onValueChange={async (value) => {
        if (
          useWorkspace.getState().dirty &&
          !(await askConfirm({
            title: "切换报告",
            description: "切换报告将放弃未保存的修改。",
            confirmLabel: "放弃修改并切换",
            destructive: true,
          }))
        )
          return;
        useWorkspace.getState().openReport(Number(value));
      }}
      options={[
        ...(id ? [] : [{ value: "", label: "暂无报告" }]),
        ...(report.data && !reports.data?.items.some((r) => r.id === report.data.id)
          ? [{ value: String(report.data.id), label: report.data.title }]
          : []),
        ...(reports.data?.items.map((r) => ({ value: String(r.id), label: r.title })) ?? []),
      ]}
    />
  );
  const ready = report.data && !report.isError;
  return (
    <div className="flex flex-1 flex-col gap-3">
      {syncError && <Notice>无法同步当前报告，请重试</Notice>}
      {reports.isError && <Notice>无法加载报告列表</Notice>}
      {writing && (
        <p role="status" className="animate-pulse">
          <StatusBadge tone="info">正在撰写…</StatusBadge>
        </p>
      )}
      {!ready && switcher}
      {id && report.isPending && (
        <div role="status" aria-label="正在加载报告…" className="space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-40" />
        </div>
      )}
      {id && report.isError && (
        <Notice>
          {report.error.message === "REPORT_NOT_FOUND" ? "报告已删除" : "无法加载报告"}
        </Notice>
      )}
      {ready && (
        <ReportContent
          key={report.data.id}
          report={report.data}
          conversationId={conversationId}
          switcher={switcher}
        />
      )}
    </div>
  );
}

function ReportContent({
  report,
  conversationId,
  switcher,
}: {
  report: Report;
  conversationId: number;
  switcher: ReactNode;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(report.title);
  const [markdown, setMarkdown] = useState(report.markdown);
  const [base, setBase] = useState(report.version);
  const [initial, setInitial] = useState({ title: report.title, markdown: report.markdown });
  const [preview, setPreview] = useState(false);
  const [history, setHistory] = useState(false);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [conflict, setConflict] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const revisions = useReportRevisions(report.id);
  const revision = useReportRevision(report.id, revisionId);
  const { save, remove, restore } = useReportActions(report.id, conversationId);
  const dirty = editing && (title !== initial.title || markdown !== initial.markdown);
  useEffect(() => {
    useWorkspace.getState().setEditing(editing);
    return () => useWorkspace.getState().setEditing(false);
  }, [editing]);
  useEffect(() => {
    useWorkspace.getState().setDirty(dirty);
    return () => useWorkspace.getState().setDirty(false);
  }, [dirty]);
  function start() {
    setTitle(report.title);
    setMarkdown(report.markdown);
    setInitial({ title: report.title, markdown: report.markdown });
    setBase(report.version);
    setEditing(true);
    setHistory(false);
    setError("");
  }
  async function submit(version: number) {
    setError("");
    try {
      await save.mutateAsync({ base_version: version, title, markdown });
      setConflict(null);
      setEditing(false);
    } catch (err) {
      if (err instanceof Error && err.message === "VERSION_CONFLICT") {
        try {
          const { data } = await api.GET("/api/reports/{report_id}", {
            params: { path: { report_id: report.id } },
          });
          if (data) setConflict(data);
          else setError("无法载入最新版本，请重试保存");
        } catch {
          setError("无法载入最新版本，请重试保存");
        }
      } else setError("保存失败，请重试");
    }
  }
  const basis = report.basis
    ? `基于 ${report.basis.contents} 条内容、${report.basis.comments} 条评论 · ${report.basis.dataset_name} · `
    : "";
  return (
    <div className="flex flex-1 flex-col gap-3">
      {editing ? (
        switcher
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="min-w-40 flex-1">{switcher}</div>
          <Button variant="outline" size="sm" onClick={start}>
            编辑
          </Button>
          <Button
            variant={history ? "secondary" : "outline"}
            size="sm"
            aria-pressed={history}
            onClick={() => setHistory(!history)}
          >
            历史版本
          </Button>
          <ReportExportMenu reportId={report.id} />
          {/* 非模态：菜单项里还要弹确认框，模态菜单收起时会把 body 的 pointer-events 留在 none。 */}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="更多操作">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                variant="destructive"
                disabled={!revisions.data || remove.isPending}
                onSelect={async () => {
                  const confirmed = await askConfirm({
                    title: "删除报告",
                    description: `连同 ${revisions.data?.length ?? 0} 个历史版本一起删除，无法恢复。`,
                    confirmLabel: "删除",
                    destructive: true,
                  });
                  if (!confirmed) return;
                  try {
                    await remove.mutateAsync();
                  } catch {
                    setError("删除失败，请重试");
                  }
                }}
              >
                删除报告
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
      {(report.new_since ?? 0) > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-brand-muted px-4 py-2.5 text-brand">
          <p>数据集自本报告以来新增 {report.new_since} 条</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              useComposer.getState().prefill(`数据集有新内容，请更新报告「${report.title}」`)
            }
          >
            让 Agent 更新
          </Button>
        </div>
      )}
      {editing && report.version > base && report.updated_by === "agent" && (
        <p role="status">
          <StatusBadge tone="warning">Agent 已更新此报告（第 {report.version} 版）</StatusBadge>
        </p>
      )}
      {error && <Notice>{error}</Notice>}
      {editing ? (
        <>
          <FormRow label="标题" stacked>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </FormRow>
          <Tabs
            value={preview ? "preview" : "edit"}
            onValueChange={(value) => setPreview(value === "preview")}
          >
            <TabsList>
              <TabsTrigger value="edit">编辑</TabsTrigger>
              <TabsTrigger value="preview">预览</TabsTrigger>
            </TabsList>
            <TabsContent value="edit">
              <FormRow label="Markdown 源码" stacked>
                <Textarea
                  className="min-h-96 font-mono text-[13px] md:text-[13px]"
                  value={markdown}
                  onChange={(e) => setMarkdown(e.target.value)}
                />
              </FormRow>
            </TabsContent>
            <TabsContent value="preview">
              <ReportMarkdown
                markdown={markdown}
                citations={report.citations}
                primaryDatasetId={report.dataset_id}
              />
            </TabsContent>
          </Tabs>
          {conflict && (
            <div
              role="dialog"
              aria-label="保存冲突"
              className="space-y-3 rounded-2xl bg-warning-muted p-4"
            >
              <p className="font-medium text-warning">报告已更新，请选择如何处理</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="min-w-0 space-y-1">
                  <h4 className="text-xs font-medium text-muted-foreground">我的修改</h4>
                  <pre className="max-h-64 overflow-auto rounded-xl bg-card p-3 text-xs whitespace-pre-wrap">
                    {title}
                    {"\n"}
                    {markdown}
                  </pre>
                </div>
                <div className="min-w-0 space-y-1">
                  <h4 className="text-xs font-medium text-muted-foreground">
                    最新版本（第 {conflict.version} 版）
                  </h4>
                  <pre className="max-h-64 overflow-auto rounded-xl bg-card p-3 text-xs whitespace-pre-wrap">
                    {conflict.title}
                    {"\n"}
                    {conflict.markdown}
                  </pre>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    client.setQueryData(["report", report.id], conflict);
                    setConflict(null);
                    setEditing(false);
                  }}
                >
                  放弃我的修改
                </Button>
                <Button
                  size="sm"
                  disabled={save.isPending}
                  onClick={() => void submit(conflict.version)}
                >
                  用我的覆盖
                </Button>
              </div>
            </div>
          )}
          <div className="sticky bottom-0 -mx-4 mt-auto -mb-4 flex justify-end gap-2 border-t bg-card px-4 py-3">
            <Button
              variant="outline"
              onClick={() => {
                setEditing(false);
                setConflict(null);
              }}
            >
              取消
            </Button>
            <Button disabled={!dirty || save.isPending} onClick={() => void submit(base)}>
              保存
            </Button>
          </div>
        </>
      ) : history ? (
        <div className="space-y-3">
          {revisions.isError && <Notice>无法加载历史版本</Notice>}
          <ItemGroup className="gap-1.5">
            {revisions.data?.map((r) => (
              <Item
                key={r.id}
                asChild
                size="sm"
                variant="muted"
                className={cn(
                  "w-full rounded-2xl text-left",
                  r.id === revisionId && "bg-brand-muted text-brand",
                )}
              >
                <Button variant={null} size={null} onClick={() => setRevisionId(r.id)}>
                  <ItemContent>
                    <ItemTitle>第 {r.version} 版</ItemTitle>
                    <ItemDescription>
                      {r.source === "agent" ? "Agent" : "我"} · {formatDateTime(r.created_at)}
                    </ItemDescription>
                  </ItemContent>
                </Button>
              </Item>
            ))}
          </ItemGroup>
          {revision.isError && <Notice>无法加载历史版本</Notice>}
          {revision.data && (
            <div className="mx-auto w-full max-w-[70ch] space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xl font-semibold tracking-tight">{revision.data.title}</h4>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={restore.isPending}
                  onClick={async () => {
                    const confirmed = await askConfirm({
                      title: "恢复此版本",
                      description: "恢复会生成新版本。",
                      confirmLabel: "恢复",
                    });
                    if (!confirmed) return;
                    try {
                      await restore.mutateAsync({
                        revisionId: revision.data.id,
                        baseVersion: report.version,
                      });
                      setHistory(false);
                      setRevisionId(null);
                    } catch {
                      setError("恢复失败，报告可能已更新，请重试");
                    }
                  }}
                >
                  恢复此版本
                </Button>
              </div>
              <ReportMarkdown
                markdown={revision.data.markdown}
                citations={report.citations}
                primaryDatasetId={report.dataset_id}
              />
            </div>
          )}
        </div>
      ) : (
        <article className="mx-auto w-full max-w-[70ch] space-y-1 pt-2">
          <h3 className="text-2xl font-semibold tracking-tight">{report.title}</h3>
          <p className="pb-3 text-xs text-muted-foreground">
            {basis}更新于 {formatDateTime(report.updated_at)}
          </p>
          <ReportMarkdown
            markdown={report.markdown}
            citations={report.citations}
            primaryDatasetId={report.dataset_id}
          />
        </article>
      )}
    </div>
  );
}
