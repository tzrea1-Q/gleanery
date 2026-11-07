import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { components } from "./schema";

type PlanPatch = components["schemas"]["PlanPatch"];
export function usePlans(conversationId: number | undefined) {
  return useQuery({
    queryKey: ["plans", conversationId],
    enabled: !!conversationId,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/plans", {
        params: { query: { conversation_id: conversationId! } },
      });
      if (!response.ok || !data) throw new Error("无法加载计划");
      return data;
    },
  });
}
export function usePlan(id: number | undefined) {
  return useQuery({
    queryKey: ["plan", id],
    enabled: !!id,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/plans/{plan_id}", {
        params: { path: { plan_id: id! } },
      });
      if (!response.ok || !data) throw new Error("无法加载计划");
      return data;
    },
  });
}
export function useSavePlan(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: PlanPatch) => {
      const { data, error, response } = await api.PATCH("/api/plans/{plan_id}", {
        params: { path: { plan_id: id } },
        body,
      });
      if (!response.ok || !data)
        throw new Error(error && "code" in error ? error.code : "保存失败");
      return data;
    },
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["plan"] }),
        client.invalidateQueries({ queryKey: ["plans"] }),
      ]);
    },
  });
}
export function useTasks(query: { plan_id?: number; conversation_id?: number }) {
  return useQuery({
    queryKey: ["tasks", query],
    enabled: !!(query.plan_id || query.conversation_id),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tasks", { params: { query } });
      if (!response.ok || !data) throw new Error("无法加载任务");
      return data;
    },
  });
}
export function useTaskAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "pause" | "resume" | "stop" }) => {
      const params = { path: { task_id: id } };
      const result =
        action === "pause"
          ? await api.POST("/api/tasks/{task_id}/pause", { params })
          : action === "resume"
            ? await api.POST("/api/tasks/{task_id}/resume", { params })
            : await api.POST("/api/tasks/{task_id}/stop", { params });
      if (!result.response.ok) throw new Error("操作失败");
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
export function useDatasets() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/datasets");
      if (!response.ok || !data) throw new Error("无法加载数据集");
      return data;
    },
  });
}
export function useContents(id: number | undefined, limit = 20, offset = 0) {
  return useQuery({
    queryKey: ["contents", id, limit, offset],
    enabled: !!id,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/datasets/{dataset_id}/contents", {
        params: { path: { dataset_id: id! }, query: { limit, offset } },
      });
      if (!response.ok || !data) throw new Error("无法加载数据集内容");
      return data;
    },
  });
}
