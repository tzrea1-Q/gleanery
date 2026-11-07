import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const tones: Record<StatusTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-brand-muted text-brand",
  success: "bg-success-muted text-success",
  warning: "bg-warning-muted text-warning",
  danger: "bg-attention-muted text-attention",
};

export function StatusBadge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: StatusTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex w-fit shrink-0 items-center rounded-full px-2 text-xs leading-5 font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
