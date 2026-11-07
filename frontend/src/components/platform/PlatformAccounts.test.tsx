import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { pickOption } from "@/test/select";
import { server } from "@/test/server";
import { PlatformAccounts, PlatformAttention } from "./PlatformAccounts";

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
      <PlatformAccounts />
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
      <PlatformAccounts />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: `B 站 · ${label}` })).toBeInTheDocument();
});

function renderAccounts(children = <PlatformAccounts />) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>,
  );
}

test("要处理的平台排在前面，可以按状态筛选和搜索", async () => {
  server.use(
    http.get("*/api/platforms", () =>
      HttpResponse.json([
        { ...base, state: "normal" },
        { ...base, platform: "xhs", state: "login_required" },
      ]),
    ),
  );
  renderAccounts();
  const user = userEvent.setup();
  const cards = await screen.findAllByRole("heading", { level: 2 });
  expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
    "小红书 · 需要登录",
    "B 站 · 正常",
  ]);
  expect(screen.getByText("共 2 个平台，1 个需要处理")).toBeInTheDocument();
  await pickOption(user, "状态筛选", "需要处理");
  expect(screen.queryByRole("region", { name: "B 站" })).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索平台"), "知乎");
  expect(await screen.findByText("没有符合条件的平台")).toBeInTheDocument();
});

test("操作失败只显示在对应平台的卡片上", async () => {
  server.use(
    http.get("*/api/platforms", () =>
      HttpResponse.json([
        { ...base, state: "normal" },
        { ...base, platform: "xhs", state: "normal" },
      ]),
    ),
    http.post("*/api/platforms/bili/probe", () =>
      HttpResponse.json({ code: "FAILED", message: "探活失败", hint: null }, { status: 500 }),
    ),
  );
  renderAccounts();
  const user = userEvent.setup();
  const bili = await screen.findByRole("region", { name: "B 站" });
  await user.click(within(bili).getByRole("button", { name: "探活" }));
  expect(await within(bili).findByRole("alert")).toBeInTheDocument();
  const xhs = screen.getByRole("region", { name: "小红书" });
  expect(within(xhs).queryByRole("alert")).not.toBeInTheDocument();
});

test("侧栏提醒只数要用户动手的平台", async () => {
  server.use(
    http.get("*/api/platforms", () =>
      HttpResponse.json([
        { ...base, state: "cooldown" },
        { ...base, platform: "xhs", state: "login_required" },
      ]),
    ),
  );
  renderAccounts(<PlatformAttention />);
  expect(await screen.findByText("，1 个平台需要处理")).toBeInTheDocument();
});
