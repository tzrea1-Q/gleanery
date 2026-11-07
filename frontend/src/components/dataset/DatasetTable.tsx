import { Fragment, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ContentFilter, ContentSort } from "@/api/dataset-types";
import { useComments, useContent, useDatasetContents } from "@/api/queries-dataset";
import { useWorkspace } from "@/stores/workspace";
import { ExportButton } from "./ExportButton";

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
      if (
        !window.confirm(
          `移出 ${impact.data.removed} 条内容，回收 ${impact.data.recycled_contents} 条内容和 ${impact.data.recycled_comments} 条评论。确认移出？`,
        )
      )
        return;
      const result = await api.POST("/api/datasets/{dataset_id}/remove", { params, body });
      if (!result.response.ok) throw new Error();
      setSelected([]);
      await client.invalidateQueries({ queryKey: ["dataset-contents", id] });
    } catch {
      setMessage("移出失败，请重试");
    }
  }
  return (
    <section aria-label={preview ? "数据集预览" : "数据集内容"} className="space-y-2 overflow-auto">
      {!preview && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm [&_input]:ml-1 [&_input]:rounded [&_input]:border [&_input]:px-1 [&_select]:ml-1 [&_select]:rounded [&_select]:border [&_button]:rounded [&_button]:border [&_button]:px-2">
          <label>
            关键词
            <input
              value={filter.keyword ?? ""}
              onChange={(e) => updateFilter({ keyword: e.target.value || undefined })}
            />
          </label>
          <label>
            平台
            <select
              value={filter.platform ?? ""}
              onChange={(e) =>
                updateFilter({
                  platform: (e.target.value || undefined) as ContentFilter["platform"],
                })
              }
            >
              <option value="">全部</option>
              <option value="bili">B 站</option>
              <option value="xhs">小红书</option>
            </select>
          </label>
          <label>
            完整度
            <select
              value={filter.completeness ?? ""}
              onChange={(e) =>
                updateFilter({
                  completeness: (e.target.value || undefined) as ContentFilter["completeness"],
                })
              }
            >
              <option value="">全部</option>
              <option value="summary">仅摘要</option>
              <option value="detail">详情</option>
            </select>
          </label>
          <label>
            发布时间起
            <input
              type="date"
              value={filter.published_from ?? ""}
              onChange={(e) => updateFilter({ published_from: e.target.value || undefined })}
            />
          </label>
          <label>
            发布时间止
            <input
              type="date"
              value={filter.published_to ?? ""}
              onChange={(e) => updateFilter({ published_to: e.target.value || undefined })}
            />
          </label>
          <label>
            点赞下限
            <input
              type="number"
              min="0"
              value={filter.min_likes ?? ""}
              onChange={(e) =>
                updateFilter({ min_likes: e.target.value ? Number(e.target.value) : undefined })
              }
            />
          </label>
          <label>
            字幕
            <select
              value={filter.has_subtitles == null ? "" : String(filter.has_subtitles)}
              onChange={(e) =>
                updateFilter({
                  has_subtitles: e.target.value ? e.target.value === "true" : undefined,
                })
              }
            >
              <option value="">全部</option>
              <option value="true">有字幕</option>
              <option value="false">无字幕</option>
            </select>
          </label>
          <label>
            排序
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as ContentSort);
                setOffset(0);
              }}
            >
              {[
                ["added_desc", "最近加入"],
                ["published_desc", "发布时间倒序"],
                ["published_asc", "发布时间正序"],
                ["likes_desc", "点赞"],
                ["plays_desc", "播放"],
                ["comments_desc", "评论"],
              ].map(([v, n]) => (
                <option key={v} value={v}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label>
            按 ID 定位
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void locateInput();
              }}
            />
          </label>
          <button onClick={() => void locateInput()}>定位</button>
          <ExportButton datasetId={id} filter={filter} sort={sort} />
          {selected.length > 0 && <button onClick={() => void remove()}>移出数据集</button>}
        </div>
      )}
      {message && <p role="alert">{message}</p>}
      {page.isError && (
        <p role="alert">
          {page.error.message === "DATASET_NOT_FOUND" ? "数据集已删除" : "无法加载数据集内容"}
        </p>
      )}
      {page.isPending && <p>正在加载数据集…</p>}
      {page.data && (
        <>
          <table className="w-full text-left text-sm [&_td]:px-1 [&_th]:px-1">
            <thead>
              <tr>
                {!preview && <th>选择</th>}
                {[
                  "标题",
                  "作者",
                  "发布时间",
                  "播放",
                  "点赞",
                  "评论",
                  "本地评论",
                  "字幕",
                  "完整度",
                ].map((x) => (
                  <th key={x} className="whitespace-nowrap">
                    {x}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.data.items.map((row) => (
                <Fragment key={row.id}>
                  <tr
                    className={`${row.completeness === "summary" ? "border-t text-muted-foreground" : "border-t"} ${highlight?.content === row.id ? "bg-yellow-100" : ""}`}
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
                      <td>
                        <input
                          aria-label={`选择内容 ${row.id}`}
                          type="checkbox"
                          checked={selected.includes(row.id)}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, row.id]
                                : selected.filter((x) => x !== row.id),
                            )
                          }
                        />
                      </td>
                    )}
                    <td>
                      {!preview && (
                        <button aria-label={`展开内容 ${row.id}`}>
                          {expanded === row.id ? "−" : "+"}
                        </button>
                      )}{" "}
                      <a
                        href={row.open_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {row.title || "无标题"}
                      </a>
                    </td>
                    <td>{row.author_nickname ?? "—"}</td>
                    <td>{row.published_at ? new Date(row.published_at).toLocaleString() : "—"}</td>
                    <Count value={row.plays} />
                    <Count value={row.likes} />
                    <Count value={row.comments} />
                    <Count value={row.local_comments} />
                    <Count value={row.platform === "bili" ? row.subtitles : null} />
                    <td className="whitespace-nowrap">
                      {row.completeness === "detail" ? "详情" : "仅摘要"}
                    </td>
                  </tr>
                  {expanded === row.id && (
                    <tr>
                      <td colSpan={10}>
                        <div className="space-y-2 border-l-2 bg-muted/30 p-3">
                          {detail.isError && <p role="alert">无法加载内容</p>}
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
                          {comments.isError && <p role="alert">无法加载评论</p>}
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
                                <div>
                                  <button
                                    disabled={!commentOffset}
                                    onClick={() =>
                                      setCommentOffset(Math.max(0, commentOffset - 20))
                                    }
                                  >
                                    上一页评论
                                  </button>{" "}
                                  <span>
                                    第 {commentOffset + 1}–
                                    {Math.min(commentOffset + 20, comments.data.total)} 条，共{" "}
                                    {comments.data.total} 条一级评论
                                  </span>{" "}
                                  <button
                                    disabled={commentOffset + 20 >= comments.data.total}
                                    onClick={() => setCommentOffset(commentOffset + 20)}
                                  >
                                    下一页评论
                                  </button>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!preview && (
            <div>
              <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - limit))}>
                上一页
              </button>{" "}
              <span>
                {page.data.filtered_total ? offset + 1 : 0}–
                {Math.min(offset + limit, page.data.filtered_total)} / {page.data.filtered_total}
              </span>{" "}
              <button
                disabled={offset + limit >= page.data.filtered_total}
                onClick={() => setOffset(offset + limit)}
              >
                下一页
              </button>
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
      className={`rounded p-1 ${highlight === item.id ? "bg-yellow-100" : ""}`}
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
    <td
      className="whitespace-nowrap tabular-nums"
      title={value == null ? undefined : String(value)}
    >
      {value == null ? "—" : compact.format(value)}
    </td>
  );
}

function duration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const s = String(seconds % 60).padStart(2, "0");
  const m = Math.floor(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
