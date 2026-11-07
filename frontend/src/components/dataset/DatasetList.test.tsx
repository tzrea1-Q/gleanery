import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useWorkspace } from "@/stores/workspace";
import { DatasetList } from "./DatasetList";

const dataset = {
  id: 1,
  name: "咖啡",
  description: "说明",
  created_in_conversation_id: 9,
  counts: { bili: 2, xhs: 1 },
  total: 3,
  created_at: 1,
  last_appended_at: 1000,
};
function setup() {
  server.use(
    http.get("*/api/datasets", () =>
      HttpResponse.json([dataset, { ...dataset, id: 2, name: "茶" }]),
    ),
  );
  // 来源对话是路由链接，要有路由上下文。
  const router = createRouter({
    routeTree: createRootRoute({ component: DatasetList }),
    history: createMemoryHistory({ initialEntries: ["/datasets"] }),
  });
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

test("显示数据集、搜索和在工作区打开", async () => {
  const user = setup();
  expect(await screen.findByText("咖啡")).toBeInTheDocument();
  expect(screen.getAllByText(/B 站 2 条，小红书 1 条；共 3 条/)).toHaveLength(2);
  expect(screen.getAllByText(new Date(1000).toLocaleString(), { exact: false })).toHaveLength(2);
  expect(screen.getAllByRole("link", { name: "对话 9" })[0]).toHaveAttribute("href", "/c/9");
  await user.type(screen.getByLabelText("搜索数据集"), "咖啡");
  expect(screen.queryByText("茶")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "打开" }));
  expect(useWorkspace.getState()).toMatchObject({ datasetId: 1, wide: true, tab: "dataset" });
});

test("编辑名称和说明并校验空名称", async () => {
  let body: unknown;
  server.use(
    http.patch("*/api/datasets/1", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(dataset);
    }),
  );
  const user = setup();
  await screen.findByText("咖啡");
  await user.click(
    within(screen.getByText("咖啡").closest("article")!).getByRole("button", { name: "编辑" }),
  );
  await user.clear(screen.getByLabelText("名称"));
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(screen.getByRole("alert")).toHaveTextContent("名称不能为空");
  await user.type(screen.getByLabelText("名称"), "新名称");
  await user.clear(screen.getByLabelText("说明"));
  await user.type(screen.getByLabelText("说明"), "新说明");
  await user.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(body).toEqual({ name: "新名称", description: "新说明" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test.each([[[]], [[12, 15]]])("删除前展示影响及进行中的任务 %s", async (active) => {
  let stop: string | null = null;
  server.use(
    http.get("*/api/datasets/1/delete-impact", () =>
      HttpResponse.json({
        reports: 2,
        contents: 3,
        comments: 8,
        recycled_contents: 2,
        recycled_comments: 5,
        tasks: 4,
        active_task_ids: active,
      }),
    ),
    http.delete("*/api/datasets/1", ({ request }) => {
      stop = new URL(request.url).searchParams.get("stop_active");
      return HttpResponse.json({});
    }),
  );
  const user = setup();
  await screen.findByText("咖啡");
  useWorkspace.getState().openDataset(1);
  await user.click(
    within(screen.getByText("咖啡").closest("article")!).getByRole("button", { name: "删除" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/将删除 3 条内容的成员关系、4 个采集任务；其中 2 条内容、5 条评论/),
  ).toHaveTextContent("删除后无法恢复");
  expect(within(dialog).getByText(/2 份报告以它为主数据集/)).toBeInTheDocument();
  if (active.length)
    expect(within(dialog).getByText("有采集任务还没结束：12、15")).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: active.length ? "停止这些任务并删除" : "确认删除" }),
  );
  await waitFor(() => expect(stop).toBe(String(!!active.length)));
  await waitFor(() => expect(useWorkspace.getState().datasetId).toBeNull());
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
