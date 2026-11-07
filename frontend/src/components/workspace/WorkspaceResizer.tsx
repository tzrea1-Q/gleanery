import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { useWorkspace } from "@/stores/workspace";

const minWidth = 320;
const minChatWidth = 340;
const keyStep = 24;

/** 放在工作区外层容器里、紧跟对话栏，靠这两个元素的实际宽度算可拖范围。 */
function measure(handle: HTMLElement) {
  const panel = handle.parentElement!;
  const width = panel.getBoundingClientRect().width;
  const chat = panel.previousElementSibling!.getBoundingClientRect().width;
  const max = Math.max(minWidth, width + chat - minChatWidth);
  return {
    grid: panel.parentElement!,
    width,
    clamp: (value: number) => Math.round(Math.min(max, Math.max(minWidth, value))),
  };
}

export function WorkspaceResizer() {
  const stored = useWorkspace((s) => s.widths[s.wide ? "wide" : "standard"]);
  const setWidth = useWorkspace((s) => s.setWidth);
  const [measured, setMeasured] = useState<number>();
  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const { grid, width, clamp } = measure(handle);
    const startX = event.clientX;
    let next: number | null = null;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("cursor-col-resize", "select-none");
    // 拖动时直接改 CSS 变量：走 store 的话每一帧都会重渲染整个对话。
    const move = (e: globalThis.PointerEvent) => {
      next = clamp(width + startX - e.clientX);
      grid.style.setProperty("--workspace-width", `${next}px`);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      document.body.classList.remove("cursor-col-resize", "select-none");
      // 只是点一下不算调整，否则会把默认宽度固定下来。
      if (next !== null) setWidth(next);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const delta = { ArrowLeft: keyStep, ArrowRight: -keyStep }[event.key];
    if (!delta) return;
    event.preventDefault();
    const { width, clamp } = measure(event.currentTarget);
    setWidth(clamp(width + delta));
  }
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="调整工作区宽度"
      aria-valuemin={minWidth}
      aria-valuenow={stored ?? measured}
      tabIndex={0}
      title="拖动调整宽度，双击恢复默认"
      className="group/resizer absolute inset-y-0 -left-3 z-10 hidden w-3 cursor-col-resize touch-none items-center justify-center outline-none md:flex"
      onFocus={(event) => setMeasured(measure(event.currentTarget).width)}
      onPointerDown={startDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => setWidth(null)}
    >
      <span className="h-10 w-1 rounded-full bg-border transition-colors group-hover/resizer:bg-brand group-focus-visible/resizer:bg-brand group-active/resizer:bg-brand" />
    </div>
  );
}
