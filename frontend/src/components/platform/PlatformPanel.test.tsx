import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { server } from "@/test/server";
import { PlatformPanel } from "./PlatformPanel";

const base = {
  platform: "bili",
  state: "locked",
  reason: null,
  cooldown_until: null,
  locked_until: Date.now() + 30000,
  quota_used: 4,
  daily_quota: 1000,
  warmup_until: null,
  last_probe_at: 1,
  last_probe_ok: false,
  last_probe_detail: "未登录",
  queue_length: 0,
  login: { phase: "failed", message: "浏览器断开", browser: "chromium" },
  browser_running: true,
};
test("平台状态、登录结果和操作随服务端刷新", async () => {
  let state = "locked";
  server.use(
    http.get("*/api/platforms", () =>
      HttpResponse.json([
        { ...base, state },
        { ...base, platform: "xhs" },
      ]),
    ),
    http.post("*/api/platforms/bili/unlock", () => {
      state = "page_changed";
      return HttpResponse.json({});
    }),
    http.post("*/api/platforms/bili/accept-page-change", () => {
      state = "normal";
      return HttpResponse.json({});
    }),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PlatformPanel />
    </QueryClientProvider>,
  );
  const bili = await screen.findByRole("region", { name: "B 站" });
  expect(within(bili).getByText(/已锁定/)).toBeInTheDocument();
  expect(within(bili).getByText(/不到 1 分钟/)).toBeInTheDocument();
  expect(within(bili).getByText(/未找到本机 Chrome/)).toBeInTheDocument();
  expect(within(bili).getByText(/失败 · 浏览器断开/)).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(within(bili).getByRole("button", { name: "解锁" }));
  await user.click(await within(bili).findByRole("button", { name: "仍然继续" }));
  expect(await within(bili).findByRole("heading", { name: "B 站 · 正常" })).toBeInTheDocument();
  // 小红书在 M4 接入，和 B 站一样显示状态与操作。
  const xhs = screen.getByRole("region", { name: "小红书" });
  expect(within(xhs).queryByText(/暂未接入/)).not.toBeInTheDocument();
  expect(within(xhs).getByRole("button", { name: "扫码登录" })).toBeInTheDocument();
});

test.each([
  ["normal", "正常"],
  ["cooldown", "冷却中"],
  ["locked", "已锁定"],
  ["login_required", "需要登录"],
  ["quota_exhausted", "今日额度用尽"],
  ["page_changed", "页面改版待确认"],
])("显示平台状态 %s", async (state, label) => {
  server.use(http.get("*/api/platforms", () => HttpResponse.json([{ ...base, state }])));
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PlatformPanel />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: `B 站 · ${label}` })).toBeInTheDocument();
});
