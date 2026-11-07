import type { ToolCallMessagePartComponent } from "@assistant-ui/react";

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
    return <p className="my-3 rounded border p-3 text-muted-foreground">正在准备 {format} 导出…</p>;
  if (result.error)
    return (
      <p role="alert" className="my-3 rounded border p-3">
        导出失败：{result.error.message}
      </p>
    );
  return (
    <section aria-label="数据集导出" className="my-3 space-y-2 rounded border p-3">
      <h3 className="font-semibold">已导出 {format}</h3>
      <p className="text-sm text-muted-foreground">
        内容 {result.contents} 条，评论 {result.comments} 条，字幕 {result.subtitles} 条
      </p>
      {result.download_url && (
        <a
          href={result.download_url}
          download={result.filename}
          aria-label={`下载 ${result.filename ?? ""}`.trim()}
          className="inline-block rounded border px-3 py-1 text-sm hover:bg-accent"
        >
          下载 {result.filename}
        </a>
      )}
    </section>
  );
};
