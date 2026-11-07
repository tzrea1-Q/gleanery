import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

/** 对话里的卡片。用 section 加 aria-label，读屏和测试都按区域找它。 */
export function ChatCard({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("my-3 space-y-4 rounded-2xl bg-card p-5", className)} {...props} />;
}
