import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationThread } from "./ConversationThread";

test("没有当前模型时显示卡片并禁用输入框", async () => {
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: null,
        disclaimer_acknowledged: true,
        credential_backend: "memory",
      }),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "先选一个模型" })).toBeInTheDocument();
  expect(await screen.findByRole("textbox")).toBeDisabled();
});

test("对话流中的模型错误显示错误卡片", async () => {
  server.use(
    http.post(
      "*/api/chat",
      () =>
        new HttpResponse(
          'data: {"type":"start"}\n\ndata: {"type":"error","errorText":"{\\"code\\":\\"MODEL_AUTH_FAILED\\",\\"message\\":\\"凭证无效\\",\\"hint\\":null}"}\n\ndata: [DONE]\n\n',
          {
            headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
          },
        ),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await userEvent.type(await screen.findByRole("textbox"), "你好{Enter}");
  expect(await screen.findByText("凭证无效")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "去设置" })).toBeInTheDocument();
});

test("409 NO_MODEL 响应显示设置入口", async () => {
  server.use(
    http.get("*/api/model-configs", () => HttpResponse.json([])),
    http.post("*/api/chat", () =>
      HttpResponse.json({ code: "NO_MODEL", message: "没有模型", hint: null }, { status: 409 }),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await userEvent.type(await screen.findByRole("textbox"), "你好{Enter}");
  expect(await screen.findByText("先选一个模型")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "去设置" })).toBeInTheDocument();
});

function sse(chunks: object[], keepOpen: boolean) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks)
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
      if (!keepOpen) {
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      }
    },
  });
  return new HttpResponse(body, {
    headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
  });
}

async function send(chunks: object[], keepOpen: boolean) {
  server.use(http.post("*/api/chat", () => sse(chunks, keepOpen)));
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await userEvent.type(await screen.findByRole("textbox"), "你好{Enter}");
}

const queryCall = {
  type: "tool-input-available",
  toolCallId: "call-1",
  toolName: "query_comments",
  input: { dataset_id: 3 },
};

test("模型还没出字时显示思考中", async () => {
  await send([{ type: "start" }, { type: "start-step" }], true);
  expect(await screen.findByRole("status", { name: "回复进度" })).toHaveTextContent("思考中…");
});

test("查询工具运行中显示正在做什么", async () => {
  await send([{ type: "start" }, { type: "start-step" }, queryCall], true);
  expect(await screen.findByRole("status", { name: "回复进度" })).toHaveTextContent(
    "正在查询评论…",
  );
});

test("回复结束后只留查询步骤，不再显示进行中", async () => {
  await send(
    [
      { type: "start" },
      { type: "start-step" },
      queryCall,
      { type: "tool-output-available", toolCallId: "call-1", output: { total: 0 } },
      { type: "finish-step" },
      { type: "start-step" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "没有评论" },
      { type: "text-end", id: "t1" },
      { type: "finish-step" },
      { type: "finish" },
    ],
    false,
  );
  expect(await screen.findByText("没有评论")).toBeInTheDocument();
  expect(screen.getByText("已查询评论")).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "回复进度" })).not.toBeInTheDocument();
});

test("后台续跑占用时禁用输入并显示提示", async () => {
  server.use(
    http.get("*/api/conversations/:id", () =>
      HttpResponse.json({
        id: 1,
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: [],
        running: "follow_up",
      }),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Agent 正在整理采集结果…")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBeDisabled();
});

test("切回仍在回复的对话时禁用输入并显示提示", async () => {
  server.use(
    http.get("*/api/conversations/:id", () =>
      HttpResponse.json({
        id: 1,
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: [],
        running: "chat",
      }),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Agent 正在回复，完成后显示…")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBeDisabled();
});

test("对话空闲时刷新后台事件和回复", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ConversationThread id="1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("textbox");
  client.setQueryData(["conversation", 1], {
    id: 1,
    title: "",
    created_at: 1,
    updated_at: 2,
    running: null,
    messages: [
      {
        id: "event-1",
        role: "user",
        parts: [{ type: "text", text: "系统事件（不是用户说的话）：测试" }],
        metadata: {
          gleanery_event: {
            type: "collection_finished",
            plan_id: 1,
            plan_title: "咖啡",
            tasks: [{ processed: 2, planned: 3 }],
            auto_run: "started",
          },
        },
      },
      { id: "reply-1", role: "assistant", parts: [{ type: "text", text: "整理完成" }] },
    ],
  });
  expect(await screen.findByText(/采集结束：计划「咖啡」/)).toBeInTheDocument();
  expect(await screen.findByText("整理完成")).toBeInTheDocument();
  expect(screen.queryByText(/系统事件/)).not.toBeInTheDocument();
});

test("后台事件让对话重挂时保留输入框里的草稿", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ConversationThread id="7" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await userEvent.type(await screen.findByRole("textbox"), "写报告");
  client.setQueryData(["conversation", 7], {
    id: 7,
    title: "",
    created_at: 1,
    updated_at: 2,
    running: null,
    messages: [{ id: "reply-1", role: "assistant", parts: [{ type: "text", text: "新回复" }] }],
  });
  expect(await screen.findByText("新回复")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("写报告");
});
