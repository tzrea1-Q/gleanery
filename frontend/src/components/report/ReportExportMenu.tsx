import { useState } from "react";
import { api } from "@/api/client";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function ReportExportMenu({ reportId }: { reportId: number }) {
  const [status, setStatus] = useState("");
  return (
    <Dialog onOpenChange={() => setStatus("")}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          导出
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>导出报告</DialogTitle>
        <DialogDescription>导出当前已保存的版本，引用转成脚注。</DialogDescription>
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
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
          </Button>
          <Button asChild>
            <a href={`/api/reports/${reportId}/export`} download>
              下载 .md
            </a>
          </Button>
        </div>
        {status === "已复制" ? (
          <p role="status" className="text-muted-foreground">
            {status}
          </p>
        ) : (
          status && <Notice>{status}</Notice>
        )}
      </DialogContent>
    </Dialog>
  );
}
