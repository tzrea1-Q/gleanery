export type CitationRef = { kind: "content" | "comment"; id: number };
export type CitationMarker = { start: number; end: number; refs: CitationRef[]; tooMany: boolean };

export function citationLabel(ref: CitationRef): string {
  return `${ref.kind === "content" ? "c" : "m"}:${ref.id}`;
}

export function parseCitations(text: string): CitationMarker[] {
  const pattern = /\[\[\s*([cm]\s*:\s*[0-9]+(?:\s*,\s*[cm]\s*:\s*[0-9]+)*)\s*\]\]/g;
  return Array.from(text.matchAll(pattern), (match) => {
    const found = Array.from(match[1].matchAll(/([cm])\s*:\s*(\d+)/g));
    const refs: CitationRef[] = [];
    const seen = new Set<string>();
    for (const item of found) {
      const ref: CitationRef = {
        kind: item[1] === "c" ? "content" : "comment",
        id: Number(item[2]),
      };
      const label = citationLabel(ref);
      if (!seen.has(label)) {
        seen.add(label);
        refs.push(ref);
      }
    }
    return {
      // JS 字符串下标（UTF-16），渲染时直接拿来切片；Python 侧按码点计。
      start: match.index,
      end: match.index + match[0].length,
      refs,
      tooMany: found.length > 10,
    };
  });
}
