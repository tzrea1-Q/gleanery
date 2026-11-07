import { useMemo } from "react";
import { TextMessagePartProvider } from "@assistant-ui/react";
import {
  MarkdownTextPrimitive,
  type MarkdownTextPrimitiveProps,
} from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import type { components } from "@/api/schema";
import { parseCitations } from "@/lib/citations";
import { Citation } from "./Citation";

type CitationOut = components["schemas"]["CitationOut"];
type Node = { type: string; value?: string; url?: string; children?: Node[] };

// 只处理 Markdown 的普通文本节点，代码和链接自身不参与替换。
function remarkCitations() {
  return (tree: Node) => {
    function visit(node: Node) {
      if (!node.children || ["link", "linkReference"].includes(node.type)) return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== "text" || !child.value) {
          visit(child);
          return [child];
        }
        const value = child.value;
        const markers = parseCitations(value);
        let cursor = 0;
        const nodes: Node[] = [];
        for (const marker of markers) {
          nodes.push({ type: "text", value: value.slice(cursor, marker.start) });
          nodes.push({
            type: "link",
            url: `citation:${marker.refs.map((ref) => `${ref.kind === "content" ? "c" : "m"}:${ref.id}`).join(",")}`,
            children: [{ type: "text", value: "原文" }],
          });
          cursor = marker.end;
        }
        nodes.push({ type: "text", value: value.slice(cursor) });
        return nodes;
      });
    }
    visit(tree);
  };
}

const remarkPlugins = [remarkGfm, remarkCitations];
const urlTransform = (url: string) => (/^(https?:|citation:)/i.test(url) ? url : "");

export function ReportMarkdown({
  markdown,
  citations,
  primaryDatasetId,
}: {
  markdown: string;
  citations: CitationOut[];
  primaryDatasetId: number | null;
}) {
  // 组件表每次都新建的话，react-markdown 会把整棵树重挂，角标按钮点不稳。
  const components = useMemo<MarkdownTextPrimitiveProps["components"]>(
    () => ({
      a: ({ href, children }) => {
        if (href?.startsWith("citation:")) {
          const refs = href
            .slice(9)
            .split(",")
            .map((part) => {
              const [kind, id] = part.split(":");
              return {
                kind: kind === "c" ? ("content" as const) : ("comment" as const),
                id: Number(id),
              };
            });
          return <Citation refs={refs} citations={citations} primaryDatasetId={primaryDatasetId} />;
        }
        return href ? (
          <a href={href} target="_blank" rel="noreferrer" className="underline">
            {children}
          </a>
        ) : (
          <>{children}</>
        );
      },
      img: ({ src, alt }) =>
        src && /^https?:\/\//i.test(src) ? (
          <a href={src} target="_blank" rel="noreferrer" className="underline">
            {alt || "图片"}
          </a>
        ) : (
          <>{alt || "图片"}</>
        ),
      table: ({ children }) => (
        <div className="overflow-x-auto">
          <table className="border-collapse border">{children}</table>
        </div>
      ),
      th: ({ children }) => <th className="border p-2">{children}</th>,
      td: ({ children }) => <td className="border p-2">{children}</td>,
    }),
    [citations, primaryDatasetId],
  );
  return (
    <TextMessagePartProvider text={markdown}>
      <MarkdownTextPrimitive
        smooth={false}
        remarkPlugins={remarkPlugins}
        urlTransform={urlTransform}
        components={components}
      />
    </TextMessagePartProvider>
  );
}
