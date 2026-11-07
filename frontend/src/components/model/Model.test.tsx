import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test, vi } from "vitest";
import { server } from "@/test/server";
import { useUiStore } from "@/stores/ui";
import { ModelSelector } from "./ModelSelector";
import { ModelErrorCard } from "./ModelErrorCard";
import { FirstRunCard } from "./FirstRunCard";
import { DisclaimerDialog } from "./DisclaimerDialog";
import { ChatgptNoticeDialog } from "./ChatgptNoticeDialog";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { TooltipProvider } from "@/components/ui/tooltip";

const configs = [
  {
    id: 2,
    name: "备用",
    status: "ok",
    favorites: [
      { name: "可用", tool_test: "ok" },
      { name: "失败", tool_test: "failed" },
    ],
  },
  {
    id: 3,
    name: "离线",
    status: "unavailable",
    favorites: [{ name: "离线模型", tool_test: "ok" }],
  },
];
function mount(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {node}
    </QueryClientProvider>,
  );
}
test("选择器只列可用模型并切换", async () => {
  let body: unknown;
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json(configs)),
    http.put("*/api/app-state/current-model", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({});
    }),
  );
  mount(<ModelSelector />);
  await userEvent.click(await screen.findByLabelText("当前模型"));
  await screen.findByRole("option", { name: "可用" });
  expect(screen.queryByRole("option", { name: "失败" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "离线模型" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "可用" }));
  await waitFor(() => expect(body).toEqual({ config_id: 2, model: "可用" }));
});
test("首次启动及使用声明", async () => {
  let ack = false;
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: null,
        disclaimer_acknowledged: ack,
        credential_backend: "memory",
      }),
    ),
    http.post("*/api/app-state/disclaimer-ack", () => {
      ack = true;
      return HttpResponse.json({});
    }),
  );
  mount(
    <>
      <FirstRunCard />
      <DisclaimerDialog />
    </>,
  );
  await userEvent.click(await screen.findByRole("button", { name: "我知道了" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(ack).toBe(true);
  expect(await screen.findByRole("heading", { name: "先选一个模型" })).toBeInTheDocument();
});
test("当前模型不可用时提示原因并能去设置", async () => {
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: {
          config_id: 1,
          config_name: "MiniMax",
          model: "m1",
          status: "unavailable",
          status_reason: "凭证无效",
        },
        disclaimer_acknowledged: true,
        credential_backend: "memory",
      }),
    ),
  );
  mount(<FirstRunCard />);
  expect(await screen.findByRole("heading", { name: "当前模型不可用" })).toBeInTheDocument();
  expect(screen.getByText("MiniMax · m1：凭证无效")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "去设置" }));
  expect(useUiStore.getState().settingsOpen).toBe(true);
});
test("需要重新连接时给出重新连接入口", async () => {
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: {
          config_id: 1,
          config_name: "ChatGPT 套餐",
          kind: "chatgpt_plan",
          model: "m1",
          status: "needs_reconnect",
          status_reason: "已断开",
        },
        disclaimer_acknowledged: true,
        credential_backend: "memory",
      }),
    ),
  );
  mount(<FirstRunCard />);
  expect(await screen.findByRole("heading", { name: "需要重新连接" })).toBeInTheDocument();
  expect(screen.getByText("ChatGPT 套餐 · m1：已断开")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "重新连接" })).toHaveAttribute(
    "href",
    "/api/chatgpt/connect",
  );
});
test.each([
  ["MODEL_AUTH_FAILED", "去设置"],
  ["MODEL_RATE_LIMITED", "换成 备用·可用 并重试"],
  ["MODEL_ERROR", "重试"],
  ["NO_MODEL", "去设置"],
])("%s 错误操作", async (code, button) => {
  server.use(http.get("*/api/model-configs", () => HttpResponse.json(configs)));
  mount(<ModelErrorCard error={JSON.stringify({ code, message: "发生错误" })} reload={vi.fn()} />);
  expect(await screen.findByRole("button", { name: button })).toBeInTheDocument();
});

test("限流后先切换模型再重试", async () => {
  const calls: string[] = [];
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json(configs)),
    http.put("*/api/app-state/current-model", async ({ request }) => {
      expect(await request.json()).toEqual({ config_id: 2, model: "可用" });
      calls.push("切换");
      return HttpResponse.json({});
    }),
  );
  mount(
    <ModelErrorCard
      error={JSON.stringify({ code: "MODEL_RATE_LIMITED", message: "限流" })}
      reload={() => calls.push("重试")}
    />,
  );
  await userEvent.click(await screen.findByRole("button", { name: "换成 备用·可用 并重试" }));
  await waitFor(() => expect(calls).toEqual(["切换", "重试"]));
});

test.each([
  ["MODEL_QUOTA_EXCEEDED", ["Manage usage", "换成 备用 并重试"]],
  ["MODEL_RECONNECT_REQUIRED", ["重新连接", "换个模型", "重试"]],
  ["MODEL_NOT_ELIGIBLE", ["换个模型"]],
  ["MODEL_UNSUPPORTED", ["去设置", "换个模型"]],
  ["MODEL_AUTH_FAILED", ["去设置", "换个模型"]],
  ["MODEL_RATE_LIMITED", ["重试", "换成 备用·可用 并重试"]],
  ["MODEL_ERROR", ["重试"]],
  ["NO_MODEL", ["去设置"]],
])("%s 显示契约按钮", async (code, labels) => {
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json(configs)),
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: { config_id: 1, model: "原模型", status: "needs_reconnect" },
      }),
    ),
  );
  mount(<ModelErrorCard error={JSON.stringify({ code, message: "出错" })} reload={() => {}} />);
  await screen.findByText(code === "NO_MODEL" ? "先选一个模型" : "出错");
  for (const label of labels)
    await screen.findByRole(label === "Manage usage" || label === "重新连接" ? "link" : "button", {
      name: label,
    });
  if (
    [
      "MODEL_UNSUPPORTED",
      "MODEL_AUTH_FAILED",
      "MODEL_NOT_ELIGIBLE",
      "MODEL_QUOTA_EXCEEDED",
      "NO_MODEL",
    ].includes(code)
  )
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
});

test("额度不足时只切换其他配置并重试", async () => {
  let switched = false;
  const reload = vi.fn();
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json(configs)),
    http.get("*/api/app-state", () =>
      HttpResponse.json({ current_model: { config_id: 1, model: "原模型", status: "ok" } }),
    ),
    http.put("*/api/app-state/current-model", async ({ request }) => {
      expect(await request.json()).toEqual({ config_id: 2, model: "可用" });
      switched = true;
      return HttpResponse.json({});
    }),
  );
  mount(
    <ModelErrorCard error={JSON.stringify({ code: "MODEL_QUOTA_EXCEEDED" })} reload={reload} />,
  );
  await userEvent.click(await screen.findByRole("button", { name: "换成 备用 并重试" }));
  await waitFor(() => expect(reload).toHaveBeenCalledOnce());
  expect(switched).toBe(true);
});

test("额度不足且没有其他配置时不显示切换按钮", async () => {
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json([configs[0]])),
    http.get("*/api/app-state", () =>
      HttpResponse.json({ current_model: { config_id: 2, model: "别的模型", status: "ok" } }),
    ),
  );
  mount(
    <ModelErrorCard error={JSON.stringify({ code: "MODEL_QUOTA_EXCEEDED" })} reload={() => {}} />,
  );
  await screen.findByRole("link", { name: "Manage usage" });
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /换成/ })).not.toBeInTheDocument(),
  );
});

test("重新连接后恢复重试按钮", async () => {
  let status = "needs_reconnect";
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json([])),
    http.get("*/api/app-state", () => HttpResponse.json({ current_model: { status } })),
  );
  render(
    <QueryClientProvider client={client}>
      <ModelErrorCard
        error={JSON.stringify({ code: "MODEL_RECONNECT_REQUIRED" })}
        reload={() => {}}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("button", { name: "重试" })).toBeDisabled();
  status = "ok";
  await client.invalidateQueries({ queryKey: ["app-state"] });
  await waitFor(() => expect(screen.getByRole("button", { name: "重试" })).toBeEnabled());
});

test.each([
  ["chatgpt_plan", true],
  ["anthropic", false],
])("%s 套餐标识显示条件", async (kind, visible) => {
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json([])),
    http.get("*/api/app-state", () =>
      HttpResponse.json({ current_model: { config_id: 1, model: "m", status: "ok", kind } }),
    ),
  );
  mount(<ModelSelector />);
  if (visible)
    expect(await screen.findByRole("link", { name: "Manage usage" })).toHaveAttribute(
      "href",
      "https://chatgpt.com/settings/usage",
    );
  else {
    await screen.findByLabelText("当前模型");
    await waitFor(() => expect(screen.queryByText("Using ChatGPT plan")).not.toBeInTheDocument());
  }
});

test("首次连接说明确认后不再显示", async () => {
  let acknowledged = false;
  server.use(
    http.get("*/api/model-configs", () =>
      HttpResponse.json([{ ...configs[0], kind: "chatgpt_plan" }]),
    ),
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        disclaimer_acknowledged: true,
        chatgpt_notice_acknowledged: acknowledged,
      }),
    ),
    http.post("*/api/app-state/chatgpt-notice-ack", () => {
      acknowledged = true;
      return HttpResponse.json({ chatgpt_notice_acknowledged: true });
    }),
  );
  mount(<ChatgptNoticeDialog />);
  await userEvent.click(await screen.findByRole("button", { name: "我知道了" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(acknowledged).toBe(true);
});

test("流出文字后出错时保留内容并标注未完成", async () => {
  server.use(
    http.post(
      "*/api/chat",
      () =>
        new HttpResponse(
          'data: {"type":"start"}\n\ndata: {"type":"text-start","id":"t"}\n\ndata: {"type":"text-delta","id":"t","delta":"已有内容"}\n\ndata: {"type":"error","errorText":"模型出错"}\n\ndata: [DONE]\n\n',
          {
            headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
          },
        ),
    ),
  );
  mount(
    <TooltipProvider>
      <ConversationThread id="1" />
    </TooltipProvider>,
  );
  await userEvent.type(await screen.findByRole("textbox"), "你好{Enter}");
  expect(await screen.findByText("已有内容")).toBeInTheDocument();
  expect(await screen.findByText("未完成")).toBeInTheDocument();
});
