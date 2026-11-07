import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { server } from "@/test/server";
import { DataSettings } from "./DataSettings";

test("数据设置、原始响应清空和停止任务后删除采集数据", async () => {
  let retention: number | null = 30;
  let stopActive = false;
  server.use(
    http.get("*/api/data-settings", () =>
      HttpResponse.json({
        raw_retention_days: retention,
        raw_count: 2,
        raw_bytes: 2048,
        db_bytes: 1048576,
      }),
    ),
    http.patch("*/api/data-settings", async ({ request }) => {
      retention = ((await request.json()) as { raw_retention_days: number | null })
        .raw_retention_days;
      return HttpResponse.json({});
    }),
    http.post("*/api/data-settings/purge-raw", () => HttpResponse.json({ deleted: 2 })),
    http.get("*/api/data/impact", () =>
      HttpResponse.json({
        datasets: 1,
        contents: 2,
        comments: 3,
        tasks: 4,
        raw_captures: 5,
        active_task_ids: [9],
      }),
    ),
    http.post("*/api/data/clear", async ({ request }) => {
      stopActive = ((await request.json()) as { stop_active: boolean }).stop_active;
      return HttpResponse.json({});
    }),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DataSettings />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  expect(await screen.findByText(/原始响应 2 条，2.00 KB/)).toBeInTheDocument();
  expect(screen.getByText(/数据库总大小 1.00 MB/)).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("原始响应留存"), "forever");
  expect(await screen.findByRole("option", { name: "永久", selected: true })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "清空全部原始响应" }));
  await user.click(
    within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认清空" }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("原始响应已清空");
  await user.click(screen.getByRole("button", { name: "删除所有采集数据" }));
  expect(await screen.findByText(/数据集 1 条、内容 2 条、评论 3 条/)).toBeInTheDocument();
  expect(screen.getByText(/对话和报告保留/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "停止这些任务并删除" }));
  expect(await screen.findByRole("status")).toHaveTextContent("采集数据已删除");
  expect(stopActive).toBe(true);
});
