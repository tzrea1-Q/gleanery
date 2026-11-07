import { useState } from "react";
import type { components } from "@/api/schema";
import { api } from "@/api/client";
import { citationLabel, type CitationRef } from "@/lib/citations";
import { useWorkspace } from "@/stores/workspace";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

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
        <sup>
          <button
            type="button"
            // Markdown 样式里 sup 的行高为 0，不给按钮自己的行高会塌成 0 高、点不到。
            className="px-0.5 text-xs leading-normal text-primary underline"
            onClick={() => (entries.length > 1 ? setView("list") : void open(entries[0].citation!))}
          >
            原文{entries.length > 1 && ` ×${entries.length}`}
          </button>
        </sup>
      )}
      {error && <span role="alert">{error}</span>}
      <Dialog
        open={view !== null}
        onOpenChange={(open) => {
          if (!open) setView(null);
        }}
      >
        <DialogContent>
          <DialogTitle>{view === "list" ? "引用列表" : "引用快照"}</DialogTitle>
          {view === "list" ? (
            <ul>
              {entries.map(({ ref, citation }) => (
                <li key={citationLabel(ref)}>
                  {citation ? (
                    <button
                      type="button"
                      className="text-left underline"
                      onClick={() => void open(citation)}
                    >
                      {details(citation)}
                    </button>
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
              <div>
                <p>{details(view)}</p>
                {view.deleted && <p>已从内容库删除</p>}
                {/^https?:\/\//i.test(view.url) && (
                  <a href={view.url} target="_blank" rel="noreferrer" className="underline">
                    打开原文
                  </a>
                )}
              </div>
            )
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
