import type { QueryClient } from "@tanstack/react-query";

export function registerReportEvents(source: EventSource, client: QueryClient) {
  for (const name of ["report.updated", "report.deleted"]) {
    source.addEventListener(name, (event) => {
      const { report_id } = JSON.parse((event as MessageEvent).data);
      for (const key of [["reports"], ["report", report_id], ["report-revisions", report_id]])
        void client.invalidateQueries({ queryKey: key });
    });
  }
  for (const name of ["dataset.deleted", "data.cleared"]) {
    source.addEventListener(name, () => {
      for (const key of ["reports", "report"]) void client.invalidateQueries({ queryKey: [key] });
    });
  }
  source.addEventListener("conversation.run", (event) => {
    const { conversation_id } = JSON.parse((event as MessageEvent).data);
    void client.invalidateQueries({ queryKey: ["conversation", conversation_id] });
  });
}
