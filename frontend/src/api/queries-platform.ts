import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { components } from "./schema";

type Platform = "bili" | "xhs";
type Update = components["schemas"]["CollectSettingsUpdate"];

export function usePlatforms() {
  return useQuery({
    queryKey: ["platforms"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/platforms");
      if (!response.ok || !data) throw new Error("无法加载平台状态");
      return data;
    },
  });
}
export function usePlatformAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      platform,
      action,
    }: {
      platform: Platform;
      action: "login" | "probe" | "unlock" | "accept-page-change";
    }) => {
      const options = { params: { path: { platform } } };
      const result =
        action === "login"
          ? await api.POST("/api/platforms/{platform}/login", options)
          : action === "probe"
            ? await api.POST("/api/platforms/{platform}/probe", options)
            : action === "unlock"
              ? await api.POST("/api/platforms/{platform}/unlock", options)
              : await api.POST("/api/platforms/{platform}/accept-page-change", options);
      if (!result.response.ok)
        throw new Error(
          result.error && "message" in result.error ? result.error.message : "操作失败，请重试",
        );
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["platforms"] }),
  });
}
export function useCollectSettings() {
  return useQuery({
    queryKey: ["collect-settings"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/collect-settings");
      if (!response.ok || !data) throw new Error("无法加载采集设置");
      return data;
    },
  });
}
export function useUpdateCollectSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Update) => {
      const { data, error, response } = await api.PATCH("/api/collect-settings", { body });
      if (!response.ok || !data) throw new Error(error?.message ?? "保存失败，请重试");
      return data;
    },
    onSuccess: (data) => client.setQueryData(["collect-settings"], data),
  });
}
export function useResetCollectSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (platform: Platform) => {
      const { data, response } = await api.POST("/api/collect-settings/{platform}/reset", {
        params: { path: { platform } },
      });
      if (!response.ok || !data) throw new Error("恢复默认失败，请重试");
      return data;
    },
    onSuccess: (data) => client.setQueryData(["collect-settings"], data),
  });
}
export function useRiskEvents(platform: Platform | "") {
  return useQuery({
    queryKey: ["risk-events", platform],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/risk-events", {
        params: { query: platform ? { platform } : {} },
      });
      if (!response.ok || !data) throw new Error("无法加载风控事件");
      return data;
    },
  });
}
