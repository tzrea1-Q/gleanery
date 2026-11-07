import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { components } from "@/api/schema";
import { Progress, duration } from "./Progress";

const base: components["schemas"]["TaskOut"] = {
  id: 1,
  plan_id: 1,
  dataset_id: 1,
  platform: "bili",
  status: "paused",
  reason: "risk",
  wait_reason: null,
  wait_until: null,
  queue_position: null,
  snapshot: {},
  progress: {
    phase: "content",
    discovered: 2,
    planned: 2,
    processed: 1,
    comments: 0,
    subtitles: 0,
    quota_counted: 1,
    skipped_missing_core: 0,
    last_log: "<b>内容</b>",
  },
  created_at: 0,
  started_at: 0,
  finished_at: null,
};

test("风控暂停显示队列说明与对应操作，日志按文本显示", () => {
  const task = base;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Progress tasks={[task]} />
    </QueryClientProvider>,
  );
  expect(screen.getByText(/风控暂停/)).toBeInTheDocument();
  expect(screen.getByText("本平台队列在你选择前不会继续")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "跳过剩余部分" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "已验证，继续（冷却后恢复）" })).toBeInTheDocument();
  expect(screen.getByText("<b>内容</b>")).toBeInTheDocument();
  expect(duration(30)).toBe("不到 1 分钟");
});

test("页面被关闭的暂停显示原因和继续按钮", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Progress tasks={[{ ...base, reason: "browser_disconnected" }]} />
    </QueryClientProvider>,
  );
  expect(screen.getByText(/已暂停（浏览器或页面被关闭）/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "继续" })).toBeInTheDocument();
});
