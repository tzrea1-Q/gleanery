import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { routeTree } from "@/routeTree.gen";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useUiStore } from "@/stores/ui";
import { server } from "./server";

function renderApp(path = "/") {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return router;
}

test("渲染对话列表，空标题显示新对话", async () => {
  renderApp();
  expect(await screen.findByRole("link", { name: "已有对话" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新对话" })).toHaveAttribute("href", "/c/2");
});

test("新建对话并导航", async () => {
  let posts = 0;
  server.use(
    http.post("*/api/conversations", () => {
      posts++;
      return HttpResponse.json({ id: 3, title: "", created_at: 1, updated_at: 1 }, { status: 201 });
    }),
  );
  const router = renderApp();
  await userEvent.click((await screen.findAllByRole("button", { name: "新对话" }))[0]);
  await waitFor(() => expect(router.state.location.pathname).toBe("/c/3"));
  expect(posts).toBe(1);
});

test("模型入口打开设置", async () => {
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: /测试模型/ }));
  expect(useUiStore.getState().settingsOpen).toBe(true);
  expect(useUiStore.getState().settingsTab).toBe("models");
});

test("没有当前模型时禁用输入框", async () => {
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({
        current_model: null,
        disclaimer_acknowledged: true,
        credential_backend: "memory",
      }),
    ),
  );
  renderApp("/c/1");
  expect(await screen.findByRole("textbox")).toBeDisabled();
});

test("登录态失效时显示整页提示", async () => {
  server.use(
    http.get("*/api/app-state", () =>
      HttpResponse.json({ code: "NO_SESSION", message: "", hint: "" }, { status: 401 }),
    ),
  );
  renderApp();
  expect(await screen.findByText("会话已失效，请重新运行 gleanery 打开应用")).toBeInTheDocument();
});

test("加载历史并只发送当前对话的最后一条消息", async () => {
  let sent:
    { id: string; trigger?: string; messages: { parts: { text?: string }[] }[] } | undefined;
  server.use(
    http.get("*/api/conversations/:id", ({ params }) =>
      HttpResponse.json({
        id: Number(params.id),
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: [
          {
            id: `history-${params.id}`,
            role: "user",
            parts: [{ type: "text", text: `历史 ${params.id}` }],
          },
        ],
      }),
    ),
    http.post("*/api/chat", async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return new HttpResponse("data: [DONE]\n\n", {
        headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
      });
    }),
  );
  renderApp("/c/1");
  expect(await screen.findByText("历史 1")).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "新对话" }));
  expect(await screen.findByText("历史 2")).toBeInTheDocument();
  expect(screen.queryByText("历史 1")).not.toBeInTheDocument();
  await user.type(screen.getByRole("textbox"), "新的消息{Enter}");
  await waitFor(() => expect(sent).toBeDefined());
  expect(sent?.id).toBe("2");
  // 后端按 trigger 判别请求类型，缺了它会 422。
  expect(sent?.trigger).toBe("submit-message");
  expect(sent?.messages).toHaveLength(1);
  expect(sent?.messages[0].parts[0].text).toBe("新的消息");
});
