import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { ContentFilter, ContentSort } from "./dataset-types";

export function useDatasetContents(
  id: number,
  filter: ContentFilter,
  sort: ContentSort,
  limit: number,
  offset: number,
) {
  return useQuery({
    queryKey: ["dataset-contents", id, filter, sort, limit, offset],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/datasets/{dataset_id}/contents", {
        params: { path: { dataset_id: id }, query: { ...filter, sort, limit, offset } },
      });
      if (!response.ok || !data)
        throw new Error(error && "code" in error ? error.code : "无法加载数据集内容");
      return data;
    },
  });
}
export function useContent(id: number | null) {
  return useQuery({
    queryKey: ["content", id],
    enabled: id !== null,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/contents/{content_id}", {
        params: { path: { content_id: id! } },
      });
      if (!response.ok || !data) throw new Error("无法加载内容");
      return data;
    },
  });
}
export function useComments(id: number | null, offset: number) {
  return useQuery({
    queryKey: ["content-comments", id, offset],
    enabled: id !== null,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/contents/{content_id}/comments", {
        params: { path: { content_id: id! }, query: { sort: "likes", limit: 20, offset } },
      });
      if (!response.ok || !data) throw new Error("无法加载评论");
      return data;
    },
  });
}
