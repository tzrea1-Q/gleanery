import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useReportActions, useReports } from "@/api/queries-report";
import type { components } from "@/api/schema";
import { useWorkspace } from "@/stores/workspace";
import { ReportExportMenu } from "./ReportExportMenu";

function ReportRow({ report }: { report: components["schemas"]["ReportSummary"] }) {
  const { remove } = useReportActions(report.id, 0);
  const [error, setError] = useState(false);
  return (
    <article className="space-y-2 rounded border p-4">
      <h2 className="font-semibold">{report.title}</h2>
      <p>主数据集：{report.dataset_name ?? "未关联数据集"}</p>
      <p>
        来源对话：
        {report.created_in_conversation_id === null ? (
          "无"
        ) : (
          <Link
            className="underline"
            to="/c/$conversationId"
            params={{ conversationId: String(report.created_in_conversation_id) }}
          >
            {report.conversation_title || `对话 ${report.created_in_conversation_id}`}
          </Link>
        )}
      </p>
      <p>
        更新于 {new Date(report.updated_at).toLocaleString()} · 第 {report.version} 版 ·
        最近修改者：{report.updated_by === "agent" ? "Agent" : "我"}
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          className="rounded border p-1"
          onClick={() => {
            useWorkspace.getState().openReport(report.id);
            useWorkspace.getState().setWide(true);
          }}
        >
          打开
        </button>
        <ReportExportMenu reportId={report.id} />
        <button
          className="rounded border p-1"
          disabled={remove.isPending}
          onClick={async () => {
            if (!window.confirm(`确定删除报告「${report.title}」及其历史版本？删除后无法恢复。`))
              return;
            try {
              setError(false);
              await remove.mutateAsync();
            } catch {
              setError(true);
            }
          }}
        >
          删除
        </button>
      </div>
      {error && <p role="alert">删除失败，请重试</p>}
    </article>
  );
}

export function ReportList() {
  const [search, setSearch] = useState("");
  const reports = useReports({ keyword: search || undefined });
  return (
    <div className="h-full space-y-4 overflow-y-auto p-6">
      <h1 className="text-xl font-semibold">所有报告</h1>
      <label>
        搜索报告
        <input
          className="ml-2 rounded border p-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      {reports.isPending ? (
        <p>正在加载报告…</p>
      ) : reports.isError ? (
        <p role="alert">无法加载报告列表</p>
      ) : reports.data.items.length ? (
        reports.data.items.map((report) => <ReportRow key={report.id} report={report} />)
      ) : (
        <p>没有找到报告</p>
      )}
    </div>
  );
}
