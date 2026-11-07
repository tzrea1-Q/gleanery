import type { QueryClient } from "@tanstack/react-query";

export function registerCollectEvents(source: EventSource, queryClient: QueryClient) {
  for (const [event, keys] of Object.entries({
    "plan.updated": ["plan", "plans"],
    "task.updated": ["tasks"],
    "dataset.updated": ["datasets", "contents"],
  })) {
    source.addEventListener(event, () => {
      for (const key of keys) void queryClient.invalidateQueries({ queryKey: [key] });
    });
  }
}
