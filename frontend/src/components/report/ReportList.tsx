import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useReportActions, useReports } from "@/api/queries-report";
import type { components } from "@/api/schema";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/stores/workspace";
import { ReportExportMenu } from "./ReportExportMenu";
import { formatDateTime } from "@/lib/format";
import { askConfirm } from "@/stores/confirm";

function ReportRow({ report }: { report: components["schemas"]["ReportSummary"] }) {
  const { remove } = useReportActions(report.id, 0);
  const [error, setError] = useState(false);
  return (
    <article className="flex flex-col gap-3 rounded-2xl bg-card p-5">
      <div>
        <h2 className="truncate text-lg font-semibold tracking-tight">{report.title}</h2>
        <p className="truncate text-muted-foreground">
          主数据集：{report.dataset_name ?? "未关联数据集"}
        </p>
      </div>
      <div className="space-y-0.5 text-xs text-muted-foreground">
        <p>
          更新于 {formatDateTime(report.updated_at)} · 第 {report.version} 版 · 最近修改者：
          {report.updated_by === "agent" ? "Agent" : "我"}
        </p>
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
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            useWorkspace.getState().openReport(report.id);
            useWorkspace.getState().setWide(true);
          }}
        >
          打开
        </Button>
        <ReportExportMenu reportId={report.id} />
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          disabled={remove.isPending}
          onClick={async () => {
            const confirmed = await askConfirm({
              title: `删除报告「${report.title}」`,
              description: "连同历史版本一起删除，删除后无法恢复。",
              confirmLabel: "删除",
              destructive: true,
            });
            if (!confirmed) return;
            try {
              setError(false);
              await remove.mutateAsync();
            } catch {
              setError(true);
            }
          }}
        >
          删除
        </Button>
      </div>
      {error && <Notice>删除失败，请重试</Notice>}
    </article>
  );
}

export function ReportList() {
  const [search, setSearch] = useState("");
  const reports = useReports({ keyword: search || undefined });
  return (
    <div className="h-full space-y-5 overflow-y-auto px-6 py-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">所有报告</h1>
          <p className="text-muted-foreground">
            {reports.data ? `共 ${reports.data.items.length} 份报告` : "Agent 写的报告都在这里"}
          </p>
        </div>
        <Input
          aria-label="搜索报告"
          placeholder="搜索报告"
          className="w-56 rounded-full border-0 bg-card shadow-none dark:bg-card"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {reports.isPending ? (
        <div role="status" aria-label="正在加载报告…" className="grid gap-3 lg:grid-cols-2">
          <Skeleton className="h-40 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      ) : reports.isError ? (
        <Notice>无法加载报告列表</Notice>
      ) : reports.data.items.length ? (
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {reports.data.items.map((report) => (
            <ReportRow key={report.id} report={report} />
          ))}
        </div>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>没有找到报告</EmptyTitle>
            <EmptyDescription>
              {search ? "换个关键词试试" : "采集结束后让 Agent 写一份，结果会出现在这里"}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}
