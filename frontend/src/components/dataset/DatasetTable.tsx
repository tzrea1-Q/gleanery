import { Fragment, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ListFilter, Search } from "lucide-react";
import { api } from "@/api/client";
import type { ContentFilter, ContentSort } from "@/api/dataset-types";
import { useComments, useContent, useDatasetContents } from "@/api/queries-dataset";
import { useWorkspace } from "@/stores/workspace";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { PlatformTag } from "@/components/common/PlatformTag";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { askConfirm } from "@/stores/confirm";
import { ExportButton } from "./ExportButton";

const sortOptions = [
  { value: "added_desc", label: "最近加入" },
  { value: "published_desc", label: "发布时间倒序" },
  { value: "published_asc", label: "发布时间正序" },
  { value: "likes_desc", label: "点赞" },
  { value: "plays_desc", label: "播放" },
  { value: "comments_desc", label: "评论" },
];

export function DatasetTable({ id, preview = false }: { id: number; preview?: boolean }) {
  const [filter, setFilter] = useState<ContentFilter>({});
  const [sort, setSort] = useState<ContentSort>("added_desc");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [commentOffset, setCommentOffset] = useState(0);
  const [highlight, setHighlight] = useState<{ content: number; comment?: number } | null>(null);
  const [input, setInput] = useState("");
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const pending = useWorkspace((s) => s.pendingFocus);
  const client = useQueryClient();
  const limit = preview ? 5 : 20;
  const page = useDatasetContents(id, filter, sort, limit, offset);
  const detail = useContent(expanded);
  const comments = useComments(expanded, commentOffset);
  function updateFilter(patch: ContentFilter) {
    setFilter((f) => ({ ...f, ...patch }));
    setOffset(0);
  }
  useEffect(() => {
    if (!pending || preview) return;
    let cancelled = false;
    async function run() {
      try {
        const target = pending!;
        const found = await api.GET("/api/locate", {
          params: {
            query: target.commentId
              ? { comment_id: target.commentId, prefer_dataset_id: target.datasetId ?? id }
              : { content_id: target.contentId, prefer_dataset_id: target.datasetId ?? id },
          },
        });
        if (!found.response.ok || !found.data) throw new Error("无法定位内容");
        if (cancelled) return;
        if (!found.data.dataset_id) {
          setMessage("这条内容已不在任何数据集里");
          useWorkspace.getState().clearFocus();
          return;
        }
        if (found.data.dataset_id !== id) {
          useWorkspace.getState().openDataset(found.data.dataset_id);
          return;
        }
        let currentFilter = filter;
        const locate = async (f: ContentFilter) =>
          api.GET("/api/datasets/{dataset_id}/contents/locate", {
            params: {
              path: { dataset_id: id },
              query: { ...f, content_id: found.data!.content_id, sort },
            },
          });
        let position = await locate(currentFilter);
        if (position.data?.offset == null) {
          currentFilter = {};
          setFilter({});
          position = await locate(currentFilter);
        }
        if (position.data?.offset == null) throw new Error("无法定位内容");
        let co = 0;
        if (target.commentId) {
          const c = await api.GET("/api/comments/{comment_id}/locate", {
            params: { path: { comment_id: target.commentId }, query: { sort: "likes" } },
          });
          if (!c.response.ok || !c.data) throw new Error("无法定位评论");
          co = Math.floor(c.data.offset / 20) * 20;
        }
        if (cancelled) return;
        setOffset(Math.floor(position.data.offset / limit) * limit);
        setExpanded(found.data.content_id);
        setCommentOffset(co);
        setHighlight({ content: found.data.content_id, comment: target.commentId });
        setMessage("");
        useWorkspace.getState().clearFocus();
      } catch {
        if (!cancelled) {
          setMessage("无法定位，请检查 ID 后重试");
          useWorkspace.getState().clearFocus();
        }
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [pending, id, preview, sort, limit]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!highlight) return;
    const node = document.querySelector(
      `[data-focus-id="${highlight.comment ? `m-${highlight.comment}` : `c-${highlight.content}`}"]`,
    );
    if (!node) return;
    node.scrollIntoView?.({ block: "center" });
    const timer = window.setTimeout(() => setHighlight(null), 3000);
    return () => window.clearTimeout(timer);
  }, [highlight, page.data, comments.data]);
  async function locateInput() {
    const match = /^(?:(c|m):)?(\d+)$/.exec(input.trim());
    if (!match || Number(match[2]) < 1) {
      setMessage("请输入有效的内容或评论 ID");
      return;
    }
    const value = Number(match[2]);
    useWorkspace
      .getState()
      .focus(
        match[1] === "m"
          ? { contentId: 0, commentId: value, datasetId: id }
          : { contentId: value, datasetId: id },
      );
  }
  async function remove() {
    try {
      const params = { path: { dataset_id: id } };
      const body = { content_ids: selected };
      const impact = await api.POST("/api/datasets/{dataset_id}/remove-impact", { params, body });
      if (!impact.response.ok || !impact.data) throw new Error();
      const confirmed = await askConfirm({
        title: "移出数据集",
        description: `移出 ${impact.data.removed} 条内容，回收 ${impact.data.recycled_contents} 条内容和 ${impact.data.recycled_comments} 条评论。`,
        confirmLabel: "确认移出",
        destructive: true,
      });
      if (!confirmed) return;
      const result = await api.POST("/api/datasets/{dataset_id}/remove", { params, body });
      if (!result.response.ok) throw new Error();
      setSelected([]);
      await client.invalidateQueries({ queryKey: ["dataset-contents", id] });
    } catch {
      setMessage("移出失败，请重试");
    }
  }
  const moreFilters = [
    filter.published_from,
    filter.published_to,
    filter.min_likes,
    filter.has_subtitles,
  ].filter((value) => value != null).length;
  // 作者和发布时间放在标题下面，表格才放得下；对话里的预览再减到三列。
  const columns: [string, boolean][] = preview
    ? [
        ["内容", false],
        ["点赞", true],
        ["评论", true],
      ]
    : [
        ["内容", false],
        ["播放", true],
        ["点赞", true],
        ["评论", true],
        ["本地评论", true],
        ["字幕", true],
        ["完整度", false],
      ];
  return (
    <section aria-label={preview ? "数据集预览" : "数据集内容"} className="space-y-3">
      {!preview && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-40 flex-1">
            <Search
              aria-hidden
              className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label="关键词"
              placeholder="搜索关键词"
              className="h-8 rounded-full border-0 bg-muted pl-8 shadow-none dark:bg-muted"
              value={filter.keyword ?? ""}
              onChange={(e) => updateFilter({ keyword: e.target.value || undefined })}
            />
          </div>
          <FormSelect
            aria-label="平台"
            size="sm"
            className="w-auto rounded-full border-0 bg-muted shadow-none dark:bg-muted"
            value={filter.platform ?? ""}
            onValueChange={(value) =>
              updateFilter({ platform: (value || undefined) as ContentFilter["platform"] })
            }
            options={[
              { value: "", label: "全部平台" },
              { value: "bili", label: "B 站" },
              { value: "xhs", label: "小红书" },
            ]}
          />
          <FormSelect
            aria-label="完整度"
            size="sm"
            className="w-auto rounded-full border-0 bg-muted shadow-none dark:bg-muted"
            value={filter.completeness ?? ""}
            onValueChange={(value) =>
              updateFilter({
                completeness: (value || undefined) as ContentFilter["completeness"],
              })
            }
            options={[
              { value: "", label: "全部完整度" },
              { value: "summary", label: "仅摘要" },
              { value: "detail", label: "详情" },
            ]}
          />
          <FormSelect
            aria-label="排序"
            size="sm"
            className="w-auto rounded-full border-0 bg-muted shadow-none dark:bg-muted"
            value={sort}
            onValueChange={(value) => {
              setSort(value as ContentSort);
              setOffset(0);
            }}
            options={sortOptions}
          />
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                <ListFilter />
                更多筛选
                {moreFilters > 0 && <span className="text-primary">{moreFilters}</span>}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 space-y-3">
              <FormRow label="发布时间起">
                <Input
                  type="date"
                  value={filter.published_from ?? ""}
                  onChange={(e) => updateFilter({ published_from: e.target.value || undefined })}
                />
              </FormRow>
              <FormRow label="发布时间止">
                <Input
                  type="date"
                  value={filter.published_to ?? ""}
                  onChange={(e) => updateFilter({ published_to: e.target.value || undefined })}
                />
              </FormRow>
              <FormRow label="点赞下限">
                <Input
                  type="number"
                  min="0"
                  value={filter.min_likes ?? ""}
                  onChange={(e) =>
                    updateFilter({
                      min_likes: e.target.value ? Number(e.target.value) : undefined,
                    })
                  }
                />
              </FormRow>
              <FormRow label="字幕">
                <FormSelect
                  value={filter.has_subtitles == null ? "" : String(filter.has_subtitles)}
                  onValueChange={(value) =>
                    updateFilter({ has_subtitles: value ? value === "true" : undefined })
                  }
                  options={[
                    { value: "", label: "全部" },
                    { value: "true", label: "有字幕" },
                    { value: "false", label: "无字幕" },
                  ]}
                />
              </FormRow>
            </PopoverContent>
          </Popover>
          <div className="flex items-center gap-1">
            <Input
              aria-label="按 ID 定位"
              placeholder="按 ID 定位"
              className="h-8 w-28 rounded-full border-0 bg-muted shadow-none dark:bg-muted"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void locateInput();
              }}
            />
            <Button variant="outline" size="sm" onClick={() => void locateInput()}>
              定位
            </Button>
          </div>
          <ExportButton datasetId={id} filter={filter} sort={sort} />
        </div>
      )}
      {selected.length > 0 && (
        <div className="flex items-center justify-between gap-2 rounded-xl bg-brand-muted px-3 py-1.5">
          <span>已选 {selected.length} 条</span>
          <Button variant="destructive" size="sm" onClick={() => void remove()}>
            移出数据集
          </Button>
        </div>
      )}
      {message && <Notice>{message}</Notice>}
      {page.isError && (
        <Notice>
          {page.error.message === "DATASET_NOT_FOUND" ? "数据集已删除" : "无法加载数据集内容"}
        </Notice>
      )}
      {page.isPending && (
        <div role="status" aria-label="正在加载数据集…" className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}
      {page.data && page.data.items.length === 0 && (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>没有内容</EmptyTitle>
            <EmptyDescription>
              {page.data.total ? "没有符合当前筛选的内容" : "这个数据集还是空的"}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {page.data && page.data.items.length > 0 && (
        <>
          <Table className="text-[13px]">
            <TableHeader className="[&_tr]:border-0">
              <TableRow className="hover:bg-transparent">
                {!preview && (
                  <TableHead className="w-7 rounded-l-xl bg-muted px-1.5">
                    <span className="sr-only">选择</span>
                  </TableHead>
                )}
                {columns.map(([name, numeric]) => (
                  <TableHead
                    key={name}
                    className={cn(
                      "h-8 bg-muted px-2 text-xs font-medium text-muted-foreground first:rounded-l-xl last:rounded-r-xl",
                      numeric && "text-right",
                    )}
                  >
                    {name}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.data.items.map((row) => (
                <Fragment key={row.id}>
                  <TableRow
                    className={cn(
                      !preview && "cursor-pointer",
                      highlight?.content === row.id && "bg-warning-muted",
                    )}
                    data-focus-id={`c-${row.id}`}
                    data-highlighted={highlight?.content === row.id ? "true" : undefined}
                    onClick={() => {
                      if (!preview) {
                        setExpanded(expanded === row.id ? null : row.id);
                        setCommentOffset(0);
                      }
                    }}
                  >
                    {!preview && (
                      <TableCell className="px-1.5" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          aria-label={`选择内容 ${row.id}`}
                          checked={selected.includes(row.id)}
                          onCheckedChange={(checked) =>
                            setSelected(
                              checked === true
                                ? [...selected, row.id]
                                : selected.filter((x) => x !== row.id),
                            )
                          }
                        />
                      </TableCell>
                    )}
                    <TableCell className="min-w-44 px-2 py-2.5 whitespace-normal">
                      <div className="flex items-start gap-1.5">
                        {!preview && (
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="mt-0.5 shrink-0"
                            aria-label={`展开内容 ${row.id}`}
                            aria-expanded={expanded === row.id}
                          >
                            <ChevronRight
                              className={cn(
                                "transition-transform",
                                expanded === row.id && "rotate-90",
                              )}
                            />
                          </Button>
                        )}
                        <div className="min-w-0">
                          <a
                            href={row.open_url}
                            target="_blank"
                            rel="noreferrer"
                            className="line-clamp-2 font-medium text-foreground hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {row.title || "无标题"}
                          </a>
                          <p
                            className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground"
                            title={row.published_at ? formatDateTime(row.published_at) : undefined}
                          >
                            <PlatformTag
                              platform={row.platform}
                              className="text-[10px] leading-4"
                            />
                            <span className="min-w-0 truncate">
                              {row.author_nickname ?? "—"}
                              {row.published_at ? ` · ${formatDate(row.published_at)}` : ""}
                            </span>
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    {!preview && <Count value={row.plays} />}
                    <Count value={row.likes} />
                    <Count value={row.comments} />
                    {!preview && <Count value={row.local_comments} />}
                    {!preview && <Count value={row.platform === "bili" ? row.subtitles : null} />}
                    {!preview && (
                      <TableCell className="px-2">
                        <StatusBadge tone={row.completeness === "detail" ? "success" : "neutral"}>
                          {row.completeness === "detail" ? "详情" : "仅摘要"}
                        </StatusBadge>
                      </TableCell>
                    )}
                  </TableRow>
                  {expanded === row.id && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={10} className="p-0 whitespace-normal">
                        <div className="space-y-2 border-l-2 border-primary/40 bg-muted/40 p-3">
                          {detail.isError && <Notice>无法加载内容</Notice>}
                          {detail.data && (
                            <>
                              <p aria-label="正文" className="whitespace-pre-wrap">
                                {detail.data.body}
                              </p>
                              {detail.data.tags.length > 0 && (
                                <p>标签：{detail.data.tags.join("、")}</p>
                              )}
                              <p>
                                投币：{detail.data.coins ?? "—"} · 弹幕：
                                {detail.data.danmaku ?? "—"} · 时长：
                                {duration(detail.data.duration_seconds)} · 分区：
                                {detail.data.category ?? "—"}
                              </p>
                              {detail.data.subtitles.map((s) => (
                                <details key={s.id}>
                                  <summary>
                                    {s.part_title} · {s.lang} ·{" "}
                                    {s.ai_generated ? "AI 生成" : "人工"} · {s.chars} 字
                                  </summary>
                                  <p className="whitespace-pre-wrap">{s.text}</p>
                                </details>
                              ))}
                            </>
                          )}
                          {comments.isError && <Notice>无法加载评论</Notice>}
                          {comments.data && (
                            <>
                              <h4 className="font-semibold">
                                评论（{comments.data.total} 条一级，{comments.data.replies_total}{" "}
                                条回复）
                              </h4>
                              {comments.data.items.map((c) => (
                                <div key={c.id}>
                                  <Comment item={c} highlight={highlight?.comment} />
                                  {(c.replies ?? []).map((r) => (
                                    <div key={r.id} className="ml-6">
                                      <Comment item={r} highlight={highlight?.comment} />
                                    </div>
                                  ))}
                                </div>
                              ))}
                              {comments.data.total > 20 && (
                                <div className="flex flex-wrap items-center gap-2">
                                  <Button
                                    variant="outline"
                                    size="xs"
                                    disabled={!commentOffset}
                                    onClick={() =>
                                      setCommentOffset(Math.max(0, commentOffset - 20))
                                    }
                                  >
                                    上一页评论
                                  </Button>
                                  <span className="text-muted-foreground">
                                    第 {commentOffset + 1}–
                                    {Math.min(commentOffset + 20, comments.data.total)} 条，共{" "}
                                    {comments.data.total} 条一级评论
                                  </span>
                                  <Button
                                    variant="outline"
                                    size="xs"
                                    disabled={commentOffset + 20 >= comments.data.total}
                                    onClick={() => setCommentOffset(commentOffset + 20)}
                                  >
                                    下一页评论
                                  </Button>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          {!preview && (
            <div className="flex items-center justify-end gap-2">
              <span className="text-muted-foreground tabular-nums">
                {page.data.filtered_total ? offset + 1 : 0}–
                {Math.min(offset + limit, page.data.filtered_total)} / {page.data.filtered_total}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - limit))}
              >
                <ChevronLeft />
                上一页
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + limit >= page.data.filtered_total}
                onClick={() => setOffset(offset + limit)}
              >
                下一页
                <ChevronRight />
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
function Comment({
  item,
  highlight,
}: {
  item: { id: number; body: string; author_nickname?: string | null; likes?: number | null };
  highlight?: number;
}) {
  return (
    <div
      className={cn("rounded p-1", highlight === item.id && "bg-warning-muted")}
      data-focus-id={`m-${item.id}`}
      data-highlighted={highlight === item.id ? "true" : undefined}
    >
      <span className="text-muted-foreground">{item.author_nickname ?? "匿名"}</span>{" "}
      <small className="text-muted-foreground">
        {item.likes != null && `赞 ${item.likes} · `}#{item.id}
      </small>
      <p className="whitespace-pre-wrap">{item.body}</p>
    </div>
  );
}

const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });

function Count({ value }: { value: number | null | undefined }) {
  return (
    <TableCell
      className="px-2 text-right tabular-nums"
      title={value == null ? undefined : String(value)}
    >
      {value == null ? "—" : compact.format(value)}
    </TableCell>
  );
}

function duration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const s = String(seconds % 60).padStart(2, "0");
  const m = Math.floor(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
