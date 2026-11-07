import type { ReactNode } from "react";
import { CircleAlert, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

/** 阻断当前区域的错误或警告，不自动消失。短暂的成功结果用 toast。 */
export function Notice({
  tone = "error",
  className,
  children,
}: {
  tone?: "error" | "warning";
  className?: string;
  children: ReactNode;
}) {
  const warning = tone === "warning";
  const Icon = warning ? TriangleAlert : CircleAlert;
  return (
    <Alert
      variant={warning ? "default" : "destructive"}
      className={cn(
        "rounded-xl",
        !warning &&
          "border-0 bg-attention-muted text-attention *:data-[slot=alert-description]:text-attention",
        warning &&
          "border-0 bg-warning-muted text-warning *:data-[slot=alert-description]:text-warning",
        className,
      )}
    >
      <Icon />
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}
