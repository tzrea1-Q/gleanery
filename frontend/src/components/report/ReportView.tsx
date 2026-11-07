import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import {
  useReport,
  useReportActions,
  useReportRevision,
  useReportRevisions,
  useReports,
} from "@/api/queries-report";
import type { components } from "@/api/schema";
import { useComposer } from "@/stores/composer";
import { useWorkspace } from "@/stores/workspace";
import { ReportMarkdown } from "./ReportMarkdown";
import { ReportExportMenu } from "./ReportExportMenu";

type Report = components["schemas"]["ReportDetail"];
const button = "rounded border px-2 py-1";

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
  return (
    <div className="space-y-3">
      {syncError && <p role="alert">无法同步当前报告，请重试</p>}
      {reports.isError && <p role="alert">无法加载报告列表</p>}
      {writing && (
        <p role="status" className="animate-pulse text-sm text-muted-foreground">
          正在撰写…
        </p>
      )}
      <label>
        报告
        <select
          className="block w-full rounded border"
          value={id ?? ""}
          onChange={(e) => {
            if (
              useWorkspace.getState().dirty &&
              !window.confirm("切换报告将放弃未保存的修改，确定切换？")
            )
              return;
            useWorkspace.getState().openReport(Number(e.target.value));
          }}
        >
          {!id && <option value="">暂无报告</option>}
          {report.data && !reports.data?.items.some((r) => r.id === report.data.id) && (
            <option value={report.data.id}>{report.data.title}</option>
          )}
          {reports.data?.items.map((r) => (
            <option key={r.id} value={r.id}>
              {r.title}
            </option>
          ))}
        </select>
      </label>
      {id && report.isPending && <p>正在加载报告…</p>}
      {id && report.isError && (
        <p role="alert">
          {report.error.message === "REPORT_NOT_FOUND" ? "报告已删除" : "无法加载报告"}
        </p>
      )}
      {report.data && !report.isError && (
        <ReportContent key={report.data.id} report={report.data} conversationId={conversationId} />
      )}
    </div>
  );
}

function ReportContent({ report, conversationId }: { report: Report; conversationId: number }) {
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
  return (
    <div className="space-y-3">
      {report.basis && (
        <p>
          基于 {report.basis.contents} 条内容、{report.basis.comments} 条评论 ·{" "}
          {report.basis.dataset_name} · 更新于 {new Date(report.updated_at).toLocaleString()}
        </p>
      )}
      {!report.basis && <p>更新于 {new Date(report.updated_at).toLocaleString()}</p>}
      {(report.new_since ?? 0) > 0 && (
        <p>
          数据集自本报告以来新增 {report.new_since} 条{" "}
          <button
            className={button}
            onClick={() =>
              useComposer.getState().prefill(`数据集有新内容，请更新报告「${report.title}」`)
            }
          >
            让 Agent 更新
          </button>
        </p>
      )}
      {editing && report.version > base && report.updated_by === "agent" && (
        <p role="status">Agent 已更新此报告（第 {report.version} 版）</p>
      )}
      {error && <p role="alert">{error}</p>}
      {editing ? (
        <>
          <label>
            标题
            <input
              className="block w-full rounded border"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <button className={button} onClick={() => setPreview(false)}>
              编辑
            </button>
            <button className={button} onClick={() => setPreview(true)}>
              预览
            </button>
          </div>
          {preview ? (
            <ReportMarkdown
              markdown={markdown}
              citations={report.citations}
              primaryDatasetId={report.dataset_id}
            />
          ) : (
            <label>
              Markdown 源码
              <textarea
                className="block min-h-64 w-full rounded border font-mono"
                value={markdown}
                onChange={(e) => setMarkdown(e.target.value)}
              />
            </label>
          )}
          <div className="flex gap-2">
            <button
              className={button}
              disabled={!dirty || save.isPending}
              onClick={() => void submit(base)}
            >
              保存
            </button>
            <button
              className={button}
              onClick={() => {
                setEditing(false);
                setConflict(null);
              }}
            >
              取消
            </button>
          </div>
        </>
      ) : (
        <>
          <h3 className="font-semibold">{report.title}</h3>
          <div className="flex flex-wrap gap-2">
            <button className={button} onClick={start}>
              编辑
            </button>
            <button className={button} onClick={() => setHistory(!history)}>
              历史版本
            </button>
            <ReportExportMenu reportId={report.id} />
            <button
              className={button}
              disabled={!revisions.data || remove.isPending}
              onClick={async () => {
                if (
                  !window.confirm(
                    `连同 ${revisions.data?.length ?? 0} 个历史版本一起删除，无法恢复。确定删除？`,
                  )
                )
                  return;
                try {
                  await remove.mutateAsync();
                } catch {
                  setError("删除失败，请重试");
                }
              }}
            >
              删除
            </button>
          </div>
          {history ? (
            <div className="space-y-2">
              {revisions.isError && <p role="alert">无法加载历史版本</p>}
              {revisions.data?.map((r) => (
                <button className="block" key={r.id} onClick={() => setRevisionId(r.id)}>
                  第 {r.version} 版 · {r.source === "agent" ? "Agent" : "我"} ·{" "}
                  {new Date(r.created_at).toLocaleString()}
                </button>
              ))}
              {revision.isError && <p role="alert">无法加载历史版本</p>}
              {revision.data && (
                <>
                  <h4>{revision.data.title}</h4>
                  <ReportMarkdown
                    markdown={revision.data.markdown}
                    citations={report.citations}
                    primaryDatasetId={report.dataset_id}
                  />
                  <button
                    className={button}
                    disabled={restore.isPending}
                    onClick={async () => {
                      if (!window.confirm("确定恢复此版本？恢复会生成新版本。")) return;
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
                  </button>
                </>
              )}
            </div>
          ) : (
            <ReportMarkdown
              markdown={report.markdown}
              citations={report.citations}
              primaryDatasetId={report.dataset_id}
            />
          )}
        </>
      )}
      {conflict && (
        <div role="dialog" aria-label="保存冲突" className="space-y-2 rounded border p-3">
          <p>报告已更新，请选择如何处理</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <h4>我的修改</h4>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap">
                {title}
                {"\n"}
                {markdown}
              </pre>
            </div>
            <div>
              <h4>最新版本（第 {conflict.version} 版）</h4>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap">
                {conflict.title}
                {"\n"}
                {conflict.markdown}
              </pre>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              className={button}
              disabled={save.isPending}
              onClick={() => void submit(conflict.version)}
            >
              用我的覆盖
            </button>
            <button
              className={button}
              onClick={() => {
                client.setQueryData(["report", report.id], conflict);
                setConflict(null);
                setEditing(false);
              }}
            >
              放弃我的修改
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
