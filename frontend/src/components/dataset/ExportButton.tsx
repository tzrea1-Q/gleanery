import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { ContentFilter, ContentSort } from "@/api/dataset-types";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

export function ExportButton({
  datasetId,
  filter,
  sort,
}: {
  datasetId: number;
  filter?: ContentFilter;
  sort?: ContentSort;
}) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState("xlsx");
  const [includeExt, setIncludeExt] = useState(false);
  const [commentLimit, setCommentLimit] = useState(20);
  const [includeSubtitles, setIncludeSubtitles] = useState(false);
  const [result, setResult] = useState<{ key: string; total: number | null } | null>(null);
  const filterKey = JSON.stringify(filter ?? {});
  const resultKey = `${datasetId}:${filterKey}`;
  const total = result?.key === resultKey ? result.total : null;
  const failed = result?.key === resultKey && result.total === null;
  useEffect(() => {
    if (!open) return;
    let active = true;
    const current = Object.fromEntries(
      Object.entries(JSON.parse(filterKey) as ContentFilter).filter(
        ([, value]) => value !== null && value !== undefined && value !== "",
      ),
    ) as ContentFilter;
    void api
      .GET("/api/datasets/{dataset_id}/contents", {
        params: { path: { dataset_id: datasetId }, query: { ...current, limit: 1 } },
      })
      .then(({ data, error }) => {
        if (active) {
          setResult({ key: resultKey, total: error || !data ? null : data.filtered_total });
        }
      })
      .catch(() => {
        if (active) setResult({ key: resultKey, total: null });
      });
    return () => {
      active = false;
    };
  }, [open, datasetId, filterKey, resultKey]);
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter ?? {})) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  if (sort) params.set("sort", sort);
  params.set("format", format);
  if (format === "md") {
    params.set("comment_limit", String(commentLimit));
    params.set("include_subtitles", String(includeSubtitles));
  } else params.set("include_ext", String(includeExt));
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setResult(null);
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <button type="button" className="rounded border p-1">
          导出
        </button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>导出数据集</DialogTitle>
        <p>
          {failed
            ? "无法获取筛选后的条数，请重试"
            : total === null
              ? "正在获取条数…"
              : `按当前筛选导出 ${total} 条`}
        </p>
        <label>
          格式{" "}
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="xlsx">Excel</option>
            <option value="csv">CSV</option>
            <option value="md">Markdown</option>
          </select>
        </label>
        {format === "md" ? (
          <>
            <label>
              评论条数{" "}
              <input
                type="number"
                min={0}
                max={200}
                value={commentLimit}
                onChange={(e) => setCommentLimit(Number(e.target.value))}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={includeSubtitles}
                onChange={(e) => setIncludeSubtitles(e.target.checked)}
              />{" "}
              包含字幕全文
            </label>
          </>
        ) : (
          <label>
            <input
              type="checkbox"
              checked={includeExt}
              onChange={(e) => setIncludeExt(e.target.checked)}
            />{" "}
            包含扩展字段
          </label>
        )}
        <a
          href={`/api/datasets/${datasetId}/export?${params}`}
          download
          onClick={(e) => {
            if (
              total === null ||
              (format === "md" &&
                (!Number.isInteger(commentLimit) || commentLimit < 0 || commentLimit > 200))
            )
              e.preventDefault();
            else setOpen(false);
          }}
          aria-disabled={total === null}
        >
          确定下载
        </a>
      </DialogContent>
    </Dialog>
  );
}
