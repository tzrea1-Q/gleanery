import type { QueryClient } from "@tanstack/react-query";

//。"contents" 是 M1 数据集表格用的 key，保留。
const KEYS: Record<string, string[]> = {
  "dataset.updated": [
    "datasets",
    "dataset",
    "contents",
    "dataset-contents",
    "content",
    "content-comments",
  ],
  "dataset.deleted": ["datasets", "dataset", "contents", "dataset-contents", "data-impact"],
  "data_settings.changed": ["data-settings"],
};

export function registerDatasetEvents(source: EventSource, queryClient: QueryClient) {
  for (const [event, keys] of Object.entries(KEYS)) {
    source.addEventListener(event, () => {
      for (const key of keys) void queryClient.invalidateQueries({ queryKey: [key] });
    });
  }
  // 删除所有采集数据后，内容、评论、数据集、计划、任务都可能变了，全部重取最省事。
  source.addEventListener("data.cleared", () => void queryClient.invalidateQueries());
}
