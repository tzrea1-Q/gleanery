import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test, vi } from "vitest";
import { server } from "@/test/server";
import { CollectSettings } from "./CollectSettings";

const limits = {
  page_interval: [3, 8],
  comment_page_interval: [2, 5],
  task_default_limit: 100,
  daily_quota: 1000,
  risk_cooldown_minutes: 30,
  min_task_gap_minutes: 10,
  page_interval_floor: 1.5,
};
test("显示字段错误、恢复默认与通知权限拒绝", async () => {
  server.use(
    http.get("*/api/collect-settings", () =>
      HttpResponse.json({
        warmup_enabled: true,
        platforms: { bili: { current: limits, defaults: limits } },
      }),
    ),
    http.get("*/api/risk-events", () => HttpResponse.json([])),
    http.patch("*/api/collect-settings", () =>
      HttpResponse.json(
        { code: "RATE_TOO_LOOSE", message: "间隔下界不能低于 1.5 秒", hint: null },
        { status: 422 },
      ),
    ),
    http.post("*/api/collect-settings/bili/reset", () =>
      HttpResponse.json({
        warmup_enabled: true,
        platforms: { bili: { current: limits, defaults: limits } },
      }),
    ),
  );
  Object.defineProperty(window, "Notification", {
    configurable: true,
    value: { requestPermission: vi.fn().mockResolvedValue("denied") },
  });
  localStorage.clear();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CollectSettings />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  const field = await screen.findByLabelText("页面间隔下界", { exact: true });
  await user.clear(field);
  await user.type(field, "1");
  const form = field.closest("form")!;
  await user.click(within(form).getByRole("button", { name: "保存" }));
  expect(await within(form).findByRole("alert")).toHaveTextContent("不能低于 1.5 秒");
  await user.click(within(form).getByRole("button", { name: "恢复默认" }));
  expect(field).toHaveValue(3);
  await user.click(screen.getByRole("checkbox", { name: "风控时发系统通知" }));
  expect(await screen.findByText(/通知权限未获授权/)).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "风控时发系统通知" })).not.toBeChecked();
  expect(localStorage.getItem("gleanery.notify-risk")).toBe("false");
});
