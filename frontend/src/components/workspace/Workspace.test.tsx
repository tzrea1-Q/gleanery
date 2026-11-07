import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { plan, tool } from "@/components/collect/test-data";
import { server } from "@/test/server";
import { useWorkspace } from "@/stores/workspace";
import { Workspace } from "./Workspace";

function setup({
  approval = false,
  conflict = false,
  reloadFailure = false,
  status = "draft",
}: {
  approval?: boolean;
  conflict?: boolean;
  reloadFailure?: boolean;
  status?: string;
} = {}) {
  let current = { ...structuredClone(plan), status };
  let patch: { base_version: number; body: typeof plan.body } | undefined;
  let approvalRequest:
    | {
        messages: { role: string; parts: { state?: string; approval?: { approved: boolean } }[] }[];
      }
    | undefined;
  server.use(
    http.get("*/api/plans", () => HttpResponse.json([current])),
    http.get("*/api/plans/1", () =>
      reloadFailure && current.version > 1
        ? HttpResponse.json({ code: "FAILED", message: "不可用" }, { status: 503 })
        : HttpResponse.json(current),
    ),
    http.get("*/api/tasks", () => HttpResponse.json([])),
    http.get("*/api/datasets", () => HttpResponse.json([])),
    http.get("*/api/model-configs", () => HttpResponse.json([])),
    http.get("*/api/conversations/:id", () =>
      HttpResponse.json({
        id: 1,
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: approval
          ? [
              {
                id: "a1",
                role: "assistant",
                parts: [
                  tool("start_collection", "approval-requested", {
                    approval: { id: "approval-1" },
                  }),
                ],
              },
            ]
          : [],
      }),
    ),
    http.patch("*/api/plans/1", async ({ request }) => {
      patch = (await request.json()) as typeof patch;
      if (conflict) {
        current = { ...current, version: 2, body: { ...current.body, title: "Agent 的新计划" } };
        return HttpResponse.json(
          { code: "VERSION_CONFLICT", message: "版本冲突", hint: null },
          { status: 409 },
        );
      }
      current = { ...current, version: 2, body: patch!.body };
      return HttpResponse.json(current);
    }),
    http.post("*/api/chat", async ({ request }) => {
      approvalRequest = (await request.json()) as typeof approvalRequest;
      return new HttpResponse(
        'data: {"type":"start"}\n\ndata: {"type":"start-step"}\n\ndata: {"type":"text-start","id":"t"}\n\ndata: {"type":"text-delta","id":"t","delta":"完成"}\n\ndata: {"type":"text-end","id":"t"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
        { headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" } },
      );
    }),
  );
  const root = createRootRoute({
    component: () => (
      <>
        <Workspace />
        <Outlet />
      </>
    ),
  });
  const route = createRoute({
    getParentRoute: () => root,
    path: "/c/$conversationId",
    component: () => <ConversationThread id="1" />,
  });
  const router = createRouter({
    routeTree: root.addChildren([route]),
    history: createMemoryHistory({ initialEntries: ["/c/1"] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { getPatch: () => patch, getApproval: () => approvalRequest };
}
afterEach(() =>
  useWorkspace.setState({
    tab: "plan",
    editing: false,
    dirty: false,
    notices: [],
    approvals: {},
    closed: false,
  }),
);
test("编辑计划后保存版本与完整内容", async () => {
  const { getPatch } = setup();
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  const quantity = await within(workspace).findByRole("spinbutton", { name: "数量" });
  await userEvent.clear(quantity);
  await userEvent.type(quantity, "2");
  await userEvent.click(within(workspace).getByRole("button", { name: "保存", exact: true }));
  await waitFor(() => expect(getPatch()?.base_version).toBe(1));
  expect(getPatch()?.body.sections[0].quantity).toBe(2);
  expect(getPatch()?.body.title).toBe("咖啡计划");
  await waitFor(() =>
    expect(within(workspace).getByRole("button", { name: "保存", exact: true })).toBeDisabled(),
  );
});
test("版本冲突重新读取最新计划并提示，下一次保存使用新版本", async () => {
  const { getPatch } = setup({ conflict: true });
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  const title = await within(workspace).findByRole("textbox", { name: "标题" });
  await userEvent.clear(title);
  await userEvent.type(title, "我的草稿");
  await userEvent.click(within(workspace).getByRole("button", { name: "保存", exact: true }));
  expect(await within(workspace).findByRole("alert")).toHaveTextContent(
    "Agent 刚改过计划，已载入最新版本",
  );
  expect(title).toHaveValue("Agent 的新计划");
  expect(getPatch()?.base_version).toBe(1);
  await userEvent.clear(title);
  await userEvent.type(title, "再次修改");
  await userEvent.click(within(workspace).getByRole("button", { name: "保存", exact: true }));
  await waitFor(() => expect(getPatch()?.base_version).toBe(2));
  await waitFor(() => expect(title).toHaveValue("Agent 的新计划"));
  await waitFor(() =>
    expect(within(workspace).getByRole("button", { name: "保存", exact: true })).toBeDisabled(),
  );
});
test("没有待审批请求时禁用确认开始并说明原因", async () => {
  setup();
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  expect(await within(workspace).findByRole("button", { name: "确认开始" })).toBeDisabled();
  expect(within(workspace).getByText(/Agent 发起审批后才能在这里确认/)).toBeInTheDocument();
});
test("工作区确认回应审批卡片的同一请求", async () => {
  const { getApproval } = setup({ approval: true });
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  const card = await screen.findByRole("region", { name: "采集审批" });
  expect(within(card).getByRole("button", { name: "批准" })).toBeEnabled();
  const confirm = await within(workspace).findByRole("button", { name: "确认开始" });
  await waitFor(() => expect(confirm).toBeEnabled());
  await userEvent.click(confirm);
  await waitFor(() => expect(getApproval()).toBeDefined());
  expect(getApproval()?.messages).toHaveLength(1);
  expect(getApproval()?.messages[0]).toMatchObject({
    role: "assistant",
    parts: [{ state: "approval-responded", approval: { id: "approval-1", approved: true } }],
  });
});

test("冲突后读取失败时保留草稿并显示重试提示", async () => {
  setup({ conflict: true, reloadFailure: true });
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  const title = await within(workspace).findByRole("textbox", { name: "标题" });
  await userEvent.clear(title);
  await userEvent.type(title, "尚未保存");
  await userEvent.click(within(workspace).getByRole("button", { name: "保存", exact: true }));
  expect(await within(workspace).findByText("无法载入最新计划，请重试保存")).toBeInTheDocument();
  expect(title).toHaveValue("尚未保存");
});
test("打开下拉选项时算正在编辑，工作区标签不被自动切走", async () => {
  setup();
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  await userEvent.click(await within(workspace).findByRole("combobox", { name: "排序" }));
  await screen.findByRole("option", { name: "热度" });
  expect(useWorkspace.getState().editing).toBe(true);
  useWorkspace.getState().auto("dataset");
  expect(useWorkspace.getState().tab).toBe("plan");
  expect(useWorkspace.getState().notices).toContain("dataset");
});

test("已确认的计划只读，下拉和勾选也不能改", async () => {
  setup({ status: "confirmed" });
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  expect(await within(workspace).findByRole("combobox", { name: "排序" })).toBeDisabled();
  expect(within(workspace).getByRole("checkbox", { name: "详情" })).toBeDisabled();
  expect(within(workspace).getByRole("textbox", { name: "标题" })).toBeDisabled();
  expect(within(workspace).queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
  expect(within(workspace).queryByRole("button", { name: "确认开始" })).not.toBeInTheDocument();
});

test("关闭后 Agent 推进阶段不会重新打开，用户点进工作区才打开", async () => {
  setup();
  const workspace = await screen.findByRole("complementary", { name: "工作区" });
  await userEvent.click(within(workspace).getByRole("button", { name: "关闭工作区" }));
  expect(useWorkspace.getState().closed).toBe(true);
  useWorkspace.getState().auto("collect");
  useWorkspace.getState().reportArrived(1);
  expect(useWorkspace.getState().closed).toBe(true);
  useWorkspace.getState().openReport(1);
  expect(useWorkspace.getState().closed).toBe(false);
});
