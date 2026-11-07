import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useUiStore } from "@/stores/ui";

export async function checkSession(response: Response) {
  if (response.status === 401) {
    const body = await response
      .clone()
      .json()
      .catch(() => null);
    if (body?.code === "NO_SESSION") useUiStore.setState({ sessionExpired: true });
  }
  return response;
}

api.use({ onResponse: ({ response }) => checkSession(response) });

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/conversations");
      if (!response.ok || !data) throw new Error("无法加载对话列表");
      return data;
    },
  });
}

export function useConversation(id: number) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/conversations/{conversation_id}", {
        params: { path: { conversation_id: id } },
      });
      if (!response.ok || !data) throw new Error("无法加载对话");
      return data;
    },
  });
}

export function useCreateConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/conversations");
      if (!response.ok || !data) throw new Error("无法新建对话");
      return data;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useAppState() {
  return useQuery({
    queryKey: ["app-state"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/app-state");
      if (!response.ok || !data) throw new Error("无法加载模型状态");
      return data;
    },
  });
}

export function useModelConfigs() {
  return useQuery({
    queryKey: ["model-configs"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/model-configs");
      if (!response.ok || !data) throw new Error("无法加载模型配置");
      return data;
    },
  });
}

export function useModelPresets() {
  return useQuery({
    queryKey: ["model-presets"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/model-presets");
      if (!response.ok || !data) throw new Error("无法加载预设");
      return data;
    },
  });
}

export function useModelMutation<T>(action: (value: T) => Promise<{ response: Response }>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (value: T) => {
      const result = await action(value);
      if (!result.response.ok) throw new Error("操作失败，请重试");
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["model-configs"] }),
        client.invalidateQueries({ queryKey: ["app-state"] }),
      ]);
    },
  });
}

export function useSetCurrentModel() {
  return useModelMutation((body: import("./schema").components["schemas"]["CurrentModelSet"]) =>
    api.PUT("/api/app-state/current-model", { body }),
  );
}

export function useAcknowledgeDisclaimer() {
  return useModelMutation(() => api.POST("/api/app-state/disclaimer-ack"));
}

export function useAcknowledgeChatgptNotice() {
  return useModelMutation(() => api.POST("/api/app-state/chatgpt-notice-ack"));
}

export function useDisconnectChatgpt() {
  return useModelMutation(() => api.POST("/api/chatgpt/disconnect"));
}
