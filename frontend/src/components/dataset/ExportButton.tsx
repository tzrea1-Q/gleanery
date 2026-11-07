import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { ContentFilter, ContentSort } from "@/api/dataset-types";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Download } from "lucide-react";
import { CheckRow } from "@/components/common/CheckRow";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
        <Button type="button" variant="outline" size="sm">
          <Download />
          导出
        </Button>
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
        <FormRow label="格式">
          <FormSelect
            value={format}
            onValueChange={setFormat}
            options={[
              { value: "xlsx", label: "Excel" },
              { value: "csv", label: "CSV" },
              { value: "md", label: "Markdown" },
            ]}
          />
        </FormRow>
        {format === "md" ? (
          <>
            <FormRow label="评论条数">
              <Input
                type="number"
                min={0}
                max={200}
                value={commentLimit}
                onChange={(e) => setCommentLimit(Number(e.target.value))}
              />
            </FormRow>
            <CheckRow
              label="包含字幕全文"
              checked={includeSubtitles}
              onCheckedChange={setIncludeSubtitles}
            />
          </>
        ) : (
          <CheckRow label="包含扩展字段" checked={includeExt} onCheckedChange={setIncludeExt} />
        )}
        <Button asChild className="w-fit justify-self-end">
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
        </Button>
      </DialogContent>
    </Dialog>
  );
}
