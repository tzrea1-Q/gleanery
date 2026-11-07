import type { QueryClient } from "@tanstack/react-query";
import { notifyRisk } from "./notify";

export function registerPlatformEvents(source: EventSource, queryClient: QueryClient) {
  for (const name of ["platform.updated", "login.updated"]) {
    source.addEventListener(
      name,
      () => void queryClient.invalidateQueries({ queryKey: ["platforms"] }),
    );
  }
  source.addEventListener("risk_event.created", (event) => {
    void queryClient.invalidateQueries({ queryKey: ["risk-events"] });
    void queryClient.invalidateQueries({ queryKey: ["platforms"] });
    const { platform } = JSON.parse((event as MessageEvent).data);
    if (platform === "bili" || platform === "xhs") notifyRisk(platform);
  });
}
