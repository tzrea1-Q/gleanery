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
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="text-brand underline underline-offset-2"
          >
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
      h1: ({ children }) => (
        <h1 className="mt-7 mb-2 text-xl font-semibold tracking-tight first:mt-0">{children}</h1>
      ),
      h2: ({ children }) => (
        <h2 className="mt-6 mb-2 text-lg font-semibold tracking-tight first:mt-0">{children}</h2>
      ),
      h3: ({ children }) => <h3 className="mt-5 mb-1.5 font-semibold first:mt-0">{children}</h3>,
      h4: ({ children }) => <h4 className="mt-4 mb-1 font-medium first:mt-0">{children}</h4>,
      p: ({ children }) => <p className="my-3 leading-7 first:mt-0 last:mb-0">{children}</p>,
      ul: ({ children }) => (
        <ul className="my-3 ms-5 list-disc space-y-1 leading-7 marker:text-muted-foreground">
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol className="my-3 ms-5 list-decimal space-y-1 leading-7 marker:text-muted-foreground">
          {children}
        </ol>
      ),
      blockquote: ({ children }) => (
        <blockquote className="my-3 rounded-xl bg-muted px-4 py-2 text-muted-foreground">
          {children}
        </blockquote>
      ),
      hr: () => <hr className="my-5" />,
      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      table: ({ children }) => (
        <div className="my-4 overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-[13px]">{children}</table>
        </div>
      ),
      th: ({ children }) => (
        <th className="bg-muted px-3 py-2 text-left font-medium first:rounded-l-lg last:rounded-r-lg">
          {children}
        </th>
      ),
      td: ({ children }) => <td className="border-b px-3 py-2 align-top">{children}</td>,
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
