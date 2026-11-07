import { useState } from "react";
import type { components } from "@/api/schema";
import { api } from "@/api/client";
import { citationLabel, type CitationRef } from "@/lib/citations";
import { useWorkspace } from "@/stores/workspace";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

type CitationOut = components["schemas"]["CitationOut"];

export function Citation({
  refs,
  citations,
  primaryDatasetId,
}: {
  refs: CitationRef[];
  citations: CitationOut[];
  primaryDatasetId: number | null;
}) {
  const [view, setView] = useState<"list" | CitationOut | null>(null);
  const [error, setError] = useState("");
  const entries = refs.map((ref) => ({
    ref,
    citation: citations.find((c) => c.kind === ref.kind && c.target_id === ref.id),
  }));
  async function open(citation: CitationOut) {
    setError("");
    if (citation.deleted) {
      setView(citation);
      return;
    }
    try {
      const { data } = await api.GET("/api/locate", {
        params: { query: { content_id: citation.content_id, prefer_dataset_id: primaryDatasetId } },
      });
      if (!data) {
        setError("无法定位引用，请重试");
        return;
      }
      if (!data.dataset_id) {
        setView(citation);
        return;
      }
      setView(null);
      useWorkspace.getState().focus({
        contentId: citation.content_id,
        ...(citation.kind === "comment" ? { commentId: citation.target_id } : {}),
        datasetId: data.dataset_id,
      });
    } catch {
      setError("无法定位引用，请重试");
    }
  }
  const details = (c: CitationOut) => (
    <>
      {c.platform === "bili" ? "B 站" : "小红书"} · {c.excerpt}
      {c.author && ` · ${c.author}`}
    </>
  );
  return (
    <>
      {entries.length === 1 && !entries[0].citation ? (
        <span className="text-muted-foreground" title={`找不到 ${citationLabel(entries[0].ref)}`}>
          失效引用
        </span>
      ) : (
        <Button
          type="button"
          variant={null}
          size={null}
          className="mx-0.5 h-[1.15rem] rounded-full bg-brand-muted px-1.5 align-[0.12em] text-[11px] leading-none font-medium text-brand hover:opacity-80"
          onClick={() => (entries.length > 1 ? setView("list") : void open(entries[0].citation!))}
        >
          原文{entries.length > 1 && ` ×${entries.length}`}
        </Button>
      )}
      {error && (
        <span role="alert" className="text-xs text-attention">
          {error}
        </span>
      )}
      <Dialog
        open={view !== null}
        onOpenChange={(open) => {
          if (!open) setView(null);
        }}
      >
        <DialogContent>
          <DialogTitle>{view === "list" ? "引用列表" : "引用快照"}</DialogTitle>
          <DialogDescription>
            {view === "list" ? "选一条跳到原始内容。" : "这条内容现在无法在数据集里定位。"}
          </DialogDescription>
          {view === "list" ? (
            <ul className="space-y-1">
              {entries.map(({ ref, citation }) => (
                <li key={citationLabel(ref)}>
                  {citation ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-auto w-full justify-start rounded-xl py-2 text-left font-normal whitespace-normal"
                      onClick={() => void open(citation)}
                    >
                      <span>{details(citation)}</span>
                    </Button>
                  ) : (
                    <span title={`找不到 ${citationLabel(ref)}`} className="text-muted-foreground">
                      失效引用（{citationLabel(ref)}）
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            view && (
              <div className="space-y-3">
                <p className="rounded-xl bg-muted p-3">{details(view)}</p>
                <div className="flex items-center justify-between gap-2">
                  {view.deleted ? (
                    <StatusBadge tone="danger">已从内容库删除</StatusBadge>
                  ) : (
                    <span />
                  )}
                  {/^https?:\/\//i.test(view.url) && (
                    <Button asChild variant="outline" size="sm">
                      <a href={view.url} target="_blank" rel="noreferrer">
                        打开原文
                      </a>
                    </Button>
                  )}
                </div>
              </div>
            )
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
