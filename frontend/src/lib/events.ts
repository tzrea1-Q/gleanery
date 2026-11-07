import type { QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { registerCollectEvents } from "./events-collect";
import { registerDatasetEvents } from "./events-dataset";
import { registerReportEvents } from "./events-report";
import { registerPlatformEvents } from "./events-platform";

export function useGlobalEvents(queryClient: QueryClient) {
  useEffect(() => {
    const source = new EventSource("/api/events");
    let opened = false;
    source.onopen = () => {
      if (opened) void queryClient.invalidateQueries();
      opened = true;
    };
    source.addEventListener("conversation.updated", (event) => {
      const { conversation_id } = JSON.parse((event as MessageEvent).data);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["conversation", conversation_id] });
    });
    source.addEventListener("conversation.deleted", () => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    });
    source.addEventListener("model_configs.changed", () => {
      void queryClient.invalidateQueries({ queryKey: ["model-configs"] });
      void queryClient.invalidateQueries({ queryKey: ["app-state"] });
    });
    source.addEventListener("app_state.changed", () => {
      void queryClient.invalidateQueries({ queryKey: ["app-state"] });
    });
    registerCollectEvents(source, queryClient);
    registerPlatformEvents(source, queryClient);
    registerDatasetEvents(source, queryClient);
    registerReportEvents(source, queryClient);
    return () => source.close();
  }, [queryClient]);
}
