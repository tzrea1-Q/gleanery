import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { registerCollectEvents } from "@/lib/events-collect";
import { useWorkspace } from "@/stores/workspace";
import { server } from "@/test/server";
import { content, dataset, plan, task, tool } from "./test-data";

function renderChat(
  parts: object[],
  options: { planData?: typeof plan; tasks?: (typeof task)[]; running?: "chat" } = {},
) {
  let currentPlan = options.planData ?? plan;
  server.use(
    http.get("*/api/conversations/:id", () =>
      HttpResponse.json({
        id: 1,
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: parts.map((part, i) => ({ id: `a${i}`, role: "assistant", parts: [part] })),
        running: options.running ?? null,
      }),
    ),
    http.get("*/api/plans/1", () => HttpResponse.json(currentPlan)),
    http.get("*/api/tasks", () => HttpResponse.json(options.tasks ?? [])),
    http.get("*/api/datasets", () => HttpResponse.json([dataset])),
    http.get("*/api/datasets/2/contents", ({ request }) => {
      expect(new URL(request.url).searchParams.get("limit")).toBe("5");
      return HttpResponse.json({ total: 1, items: [content] });
    }),
    http.get("*/api/model-configs", () => HttpResponse.json([])),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return {
    client,
    setPlan: (value: typeof plan) => {
      currentPlan = value;
    },
  };
}
afterEach(() =>
  useWorkspace.setState({ tab: "plan", editing: false, dirty: false, notices: [], approvals: {} }),
);

test("计划卡片展示草稿字段、错误和提示，并打开计划标签", async () => {
  renderChat([tool("propose_collection_plan", "output-available", { output: { plan_id: 1 } })], {
    planData: {
      ...plan,
      issues: [
        { code: "EMPTY_SECTION", message: "缺少目标", severity: "error" },
        { code: "PLATFORM_NOT_READY", message: "B 站冷却中", severity: "warning" },
      ],
    },
  });
  const card = await screen.findByRole("region", { name: "计划摘要" }, { timeout: 5000 });
  expect(within(card).getByText("咖啡计划 · 草稿")).toBeInTheDocument();
  for (const text of [
    "关键词：咖啡",
    "content:1",
    "数量 3",
    "热度",
    "近 7 天",
    "详情",
    "评论 10",
    "字幕 采集",
    "约 2 分钟",
    "缺少目标",
    "B 站冷却中",
  ])
    expect(within(card).getByText(new RegExp(text))).toBeInTheDocument();
  useWorkspace.getState().select("dataset");
  await userEvent.click(within(card).getByRole("button", { name: "在工作区编辑" }));
  expect(useWorkspace.getState().tab).toBe("plan");
});
test("同一计划出现多次时只展开最后一张，并随事件刷新为最新版本", async () => {
  const { client, setPlan } = renderChat([
    tool("propose_collection_plan", "output-available", { output: { plan_id: 1 } }),
    tool("get_collection_plan", "output-available", { output: { plan_id: 1 } }),
  ]);
  expect(await screen.findAllByText("咖啡计划 · 草稿")).toHaveLength(1);
  expect(screen.getAllByRole("region", { name: "计划摘要" })).toHaveLength(1);
  expect(screen.getByText("计划「咖啡计划」已更新，最新版本见下方")).toBeInTheDocument();
  setPlan({ ...plan, status: "confirmed", version: 2, body: { ...plan.body, title: "最新计划" } });
  const events = new EventTarget();
  registerCollectEvents(events as EventSource, client);
  events.dispatchEvent(new Event("plan.updated"));
  expect(await screen.findByText("最新计划 · 已确认")).toBeInTheDocument();
  expect(screen.getByText("计划「最新计划」已更新，最新版本见下方")).toBeInTheDocument();
});
test("版本冲突的修改不出卡片，后面成功的那次照常展开", async () => {
  renderChat([
    tool("update_collection_plan", "output-available", {
      toolCallId: "call-conflict",
      input: { plan_id: 1 },
      output: { error: { code: "VERSION_CONFLICT", message: "计划版本冲突" } },
    }),
    tool("update_collection_plan", "output-available", { output: { plan_id: 1 } }),
  ]);
  expect(await screen.findByRole("region", { name: "计划摘要" })).toBeInTheDocument();
  expect(screen.queryByText("计划版本冲突")).not.toBeInTheDocument();
});
test("计划工具错误显示错误行", async () => {
  renderChat([
    tool("get_collection_plan", "output-available", {
      output: { error: { code: "FAILED", message: "计划不可用" } },
    }),
  ]);
  expect(await screen.findByRole("alert")).toHaveTextContent("计划不可用");
});
test("待审批显示最新计划、平台和额度提示，并可填写拒绝理由", async () => {
  renderChat([tool("start_collection", "approval-requested", { approval: { id: "approval-1" } })], {
    planData: {
      ...plan,
      issues: [
        { code: "PLATFORM_NOT_READY", message: "B 站冷却中", severity: "warning" },
        { code: "QUOTA_EXCEEDED", message: "今日额度不足", severity: "warning" },
      ],
    },
  });
  const card = await screen.findByRole("region", { name: "采集审批" });
  expect(await within(card).findByText("咖啡计划 · 草稿")).toBeInTheDocument();
  expect(within(card).getByText("B 站冷却中")).toBeInTheDocument();
  expect(within(card).getByText(/超出部分明天继续/)).toBeInTheDocument();
  expect(within(card).getByRole("button", { name: "批准" })).toBeEnabled();
  expect(within(card).getByRole("textbox", { name: "拒绝理由（可选）" })).toBeInTheDocument();
});
test("切回仍在回复的对话时，待审批卡片不再给按钮", async () => {
  renderChat([tool("start_collection", "approval-requested", { approval: { id: "approval-1" } })], {
    running: "chat",
  });
  expect(await screen.findByText("Agent 正在处理…")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "采集审批" })).not.toBeInTheDocument();
});
test("批准后的运行任务显示进度", async () => {
  renderChat(
    [tool("start_collection", "output-available", { output: { plan_id: 1, dataset_id: 2 } })],
    { tasks: [task] },
  );
  const card = await screen.findByRole("region", { name: "采集进度" });
  expect(within(card).getByText(/执行中/)).toBeInTheDocument();
  expect(within(card).getByText(/实得 \/ 计划：1 \/ 3/)).toBeInTheDocument();
});
test("全部完成显示预览并能打开工作区数据集", async () => {
  renderChat([tool("start_collection", "output-available", { output: { plan_id: 1 } })], {
    tasks: [{ ...task, status: "completed" }],
  });
  const card = await screen.findByRole("region", { name: "采集结束" });
  expect(within(card).queryByText(/预计剩余时间/)).not.toBeInTheDocument();
  expect(await within(card).findByRole("link", { name: "咖啡视频" })).toHaveAttribute(
    "href",
    "https://example.com/video",
  );
  await userEvent.click(within(card).getByRole("button", { name: "在工作区查看" }));
  expect(useWorkspace.getState().tab).toBe("dataset");
});
test.each(["stopped", "failed"] as const)(
  "%s 的结束卡片将建议预填到输入框，不发送",
  async (status) => {
    let posts = 0;
    server.use(
      http.post("*/api/chat", () => {
        posts++;
        return new HttpResponse();
      }),
    );
    renderChat([tool("start_collection", "output-available", { output: { plan_id: 1 } })], {
      tasks: [{ ...task, status }],
    });
    const card = await screen.findByRole("region", { name: "采集结束" });
    const input = screen.getByPlaceholderText("给 Agent 发消息…");
    for (const text of ["用已有数据继续整理", "补采"]) {
      await userEvent.click(within(card).getByRole("button", { name: text }));
      expect(input).toHaveValue(text);
    }
    expect(posts).toBe(0);
  },
);
test("拒绝的审批保留可读状态", async () => {
  renderChat([
    tool("start_collection", "output-denied", {
      approval: { id: "approval-1", approved: false, reason: "暂不采集" },
    }),
  ]);
  expect(await screen.findByText(/已拒绝/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "采集进度" })).not.toBeInTheDocument();
});
test("开始工具错误显示错误行", async () => {
  renderChat([
    tool("start_collection", "output-available", {
      output: { error: { code: "FAILED", message: "无法开始" } },
    }),
  ]);
  expect(await screen.findByRole("alert")).toHaveTextContent("无法开始");
});
test("数据集工具显示 REST 列表", async () => {
  renderChat([tool("list_datasets", "output-available", { output: { datasets: [] } })]);
  const card = await screen.findByRole("region", { name: "数据集列表" });
  expect(await within(card).findByText("咖啡数据 · 2 条")).toBeInTheDocument();
});
test("数据集工具错误显示错误行", async () => {
  renderChat([
    tool("list_datasets", "output-available", {
      output: { error: { code: "FAILED", message: "数据集不可用" } },
    }),
  ]);
  expect(await screen.findByRole("alert")).toHaveTextContent("数据集不可用");
});

test("拒绝时把用户理由交给审批接口", async () => {
  let sent:
    { messages: { parts: { approval?: { approved: boolean; reason?: string } }[] }[] } | undefined;
  server.use(
    http.post("*/api/chat", async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return new HttpResponse(
        'data: {"type":"start"}\n\ndata: {"type":"start-step"}\n\ndata: {"type":"text-start","id":"t"}\n\ndata: {"type":"text-delta","id":"t","delta":"收到"}\n\ndata: {"type":"text-end","id":"t"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
        { headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" } },
      );
    }),
  );
  renderChat([tool("start_collection", "approval-requested", { approval: { id: "approval-1" } })]);
  const card = await screen.findByRole("region", { name: "采集审批" });
  await userEvent.type(within(card).getByRole("textbox", { name: "拒绝理由（可选）" }), "暂不采集");
  await userEvent.click(within(card).getByRole("button", { name: "拒绝" }));
  await waitFor(() => expect(sent).toBeDefined());
  expect(sent?.messages[0].parts[0].approval).toMatchObject({
    approved: false,
    reason: "暂不采集",
  });
});
