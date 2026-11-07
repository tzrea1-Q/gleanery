import { cn } from "@/lib/utils";

const names: Record<string, string> = { bili: "B 站", xhs: "小红书" };

export function platformName(platform: string) {
  return names[platform] ?? platform;
}

export function PlatformTag({ platform, className }: { platform: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded px-1.5 text-xs leading-[18px] font-semibold text-platform-foreground",
        platform === "bili" && "bg-platform-bili",
        platform === "xhs" && "bg-platform-xhs",
        platform !== "bili" && platform !== "xhs" && "bg-muted-foreground",
        className,
      )}
    >
      {platformName(platform)}
    </span>
  );
}
