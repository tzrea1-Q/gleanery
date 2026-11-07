import { useState } from "react";
import { api } from "@/api/client";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

export function ReportExportMenu({ reportId }: { reportId: number }) {
  const [status, setStatus] = useState("");
  return (
    <Dialog onOpenChange={() => setStatus("")}>
      <DialogTrigger asChild>
        <button className="rounded border px-2 py-1">导出</button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>导出报告</DialogTitle>
        <a href={`/api/reports/${reportId}/export`} download>
          下载 .md
        </a>
        <button
          onClick={async () => {
            try {
              const { data, response } = await api.GET("/api/reports/{report_id}/export", {
                params: { path: { report_id: reportId } },
                parseAs: "text",
              });
              if (!response.ok || typeof data !== "string") throw new Error();
              await navigator.clipboard.writeText(data);
              setStatus("已复制");
            } catch {
              setStatus("复制失败，请重试");
            }
          }}
        >
          复制为 Markdown
        </button>
        {status && <p role={status === "已复制" ? "status" : "alert"}>{status}</p>}
      </DialogContent>
    </Dialog>
  );
}
