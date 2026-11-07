import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { components, operations } from "./schema";

type Filter = NonNullable<operations["list_reports_api_reports_get"]["parameters"]["query"]>;
type Save = components["schemas"]["ReportSave"];
function failure(error: unknown, fallback: string): Error {
  return new Error(
    error && typeof error === "object" && "code" in error ? String(error.code) : fallback,
  );
}
export function useReports(filter: Filter) {
  return useQuery({
    queryKey: ["reports", filter],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/reports", { params: { query: filter } });
      if (!data) throw failure(error, "无法加载报告列表");
      if (filter.limit !== undefined || filter.offset !== undefined) return data;
      const items = [...data.items];
      while (items.length < data.total) {
        const page = await api.GET("/api/reports", {
          params: { query: { ...filter, offset: items.length } },
        });
        if (!page.data) throw failure(page.error, "无法加载报告列表");
        if (!page.data.items.length) break;
        items.push(...page.data.items);
      }
      return { ...data, items };
    },
  });
}
export function useReport(id: number | null) {
  return useQuery({
    queryKey: ["report", id],
    enabled: id !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/reports/{report_id}", {
        params: { path: { report_id: id! } },
      });
      if (!data) throw failure(error, "无法加载报告");
      return data;
    },
  });
}
export function useReportRevisions(id: number | null) {
  return useQuery({
    queryKey: ["report-revisions", id],
    enabled: id !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/reports/{report_id}/revisions", {
        params: { path: { report_id: id! } },
      });
      if (!data) throw failure(error, "无法加载历史版本");
      return data;
    },
  });
}
export function useReportRevision(id: number, revisionId: number | null) {
  return useQuery({
    queryKey: ["report-revision", id, revisionId],
    enabled: revisionId !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/reports/{report_id}/revisions/{revision_id}", {
        params: { path: { report_id: id, revision_id: revisionId! } },
      });
      if (!data) throw failure(error, "无法加载历史版本");
      return data;
    },
  });
}
export function useReportActions(id: number, conversationId: number) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["reports"] });
    void client.invalidateQueries({ queryKey: ["report", id] });
    void client.invalidateQueries({ queryKey: ["report-revisions", id] });
  };
  const save = useMutation({
    mutationFn: async (body: Save) => {
      const { data, error } = await api.PUT("/api/reports/{report_id}", {
        params: {
          path: { report_id: id },
          header: { "x-conversation-id": conversationId || undefined },
        },
        body,
      });
      if (!data) throw failure(error, "保存失败");
      return data;
    },
    onSuccess: (data) => {
      client.setQueryData(["report", id], data);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.DELETE("/api/reports/{report_id}", {
        params: { path: { report_id: id } },
      });
      if (!response.ok) throw failure(error, "删除失败");
    },
    onSuccess: refresh,
  });
  const restore = useMutation({
    mutationFn: async ({
      revisionId,
      baseVersion,
    }: {
      revisionId: number;
      baseVersion: number;
    }) => {
      const { data, error } = await api.POST(
        "/api/reports/{report_id}/revisions/{revision_id}/restore",
        {
          params: {
            path: { report_id: id, revision_id: revisionId },
            header: { "x-conversation-id": conversationId || undefined },
          },
          body: { base_version: baseVersion },
        },
      );
      if (!data) throw failure(error, "恢复失败");
      return data;
    },
    onSuccess: (data) => {
      client.setQueryData(["report", id], data);
      refresh();
    },
  });
  return { save, remove, restore };
}
