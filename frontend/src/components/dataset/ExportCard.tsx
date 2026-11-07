import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { ChatCard } from "@/components/common/ChatCard";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";

type Args = { dataset_id?: number; format?: string };
type Result = {
  format?: string;
  contents?: number;
  comments?: number;
  subtitles?: number;
  filename?: string;
  download_url?: string;
  error?: { code?: string; message?: string };
};

const FORMAT_TEXT: Record<string, string> = { xlsx: "Excel", csv: "CSV", md: "Markdown" };

export const ExportCard: ToolCallMessagePartComponent<Args, Result> = ({ args, result }) => {
  const format = FORMAT_TEXT[result?.format ?? args.format ?? ""] ?? "文件";
  if (!result)
    return (
      <ChatCard>
        <p className="text-muted-foreground">正在准备 {format} 导出…</p>
      </ChatCard>
    );
  if (result.error) return <Notice className="my-3">导出失败：{result.error.message}</Notice>;
  return (
    <ChatCard aria-label="数据集导出">
      <div>
        <h3 className="text-xl font-semibold tracking-tight">已导出 {format}</h3>
        <p className="text-muted-foreground">
          内容 {result.contents} 条，评论 {result.comments} 条，字幕 {result.subtitles} 条
        </p>
      </div>
      {result.download_url && (
        <Button asChild variant="outline" size="sm">
          <a
            href={result.download_url}
            download={result.filename}
            aria-label={`下载 ${result.filename ?? ""}`.trim()}
          >
            下载 {result.filename}
          </a>
        </Button>
      )}
    </ChatCard>
  );
};
