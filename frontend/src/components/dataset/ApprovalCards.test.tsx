import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { server } from "@/test/server";

test.each(["remove_from_dataset", "delete_dataset"])("%s 显示影响并传回拒绝理由", async (tool) => {
  let sent: string | undefined;
  server.use(
    http.get("*/api/conversations/:id", () =>
      HttpResponse.json({
        id: 1,
        title: "",
        created_at: 1,
        updated_at: 1,
        messages: [
          {
            id: "a1",
            role: "assistant",
            parts: [
              {
                type: `tool-${tool}`,
                toolCallId: "call-1",
                state: "approval-requested",
                input: { dataset_id: 1, content_ids: [2] },
                approval: { id: "approval-1" },
              },
            ],
          },
        ],
      }),
    ),
    http.get("*/api/datasets/1", () => HttpResponse.json({ id: 1, name: "测试数据集", total: 1 })),
    http.get("*/api/contents/2", () => HttpResponse.json({ id: 2, title: "<b>平台标题</b>" })),
    http.post("*/api/datasets/1/remove-impact", () =>
      HttpResponse.json({ removed: 1, not_member: [], recycled_contents: 1, recycled_comments: 2 }),
    ),
    http.get("*/api/datasets/1/delete-impact", () =>
      HttpResponse.json({
        reports: 2,
        contents: 1,
        comments: 2,
        recycled_contents: 1,
        recycled_comments: 2,
        tasks: 0,
        active_task_ids: [],
      }),
    ),
    http.post("*/api/chat", async ({ request }) => {
      sent = await request.text();
      return new HttpResponse(
        'data: {"type":"start"}\n\ndata: {"type":"start-step"}\n\ndata: {"type":"text-start","id":"t"}\n\ndata: {"type":"text-delta","id":"t","delta":"完成"}\n\ndata: {"type":"text-end","id":"t"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
        { headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" } },
      );
    }),
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
  expect(await screen.findByText("测试数据集")).toBeInTheDocument();
  expect(
    screen.getByText(/其中 1 条内容、2 条评论不在其他数据集里，会从内容库删除/),
  ).toBeInTheDocument();
  if (tool === "remove_from_dataset")
    expect(screen.getByText("<b>平台标题</b>")).toBeInTheDocument();
  else {
    expect(screen.getByText(/将删除 1 条内容的成员关系、0 个采集任务/)).toHaveTextContent(
      "删除后无法恢复",
    );
    expect(screen.getByText(/2 份报告以它为主数据集/)).toBeInTheDocument();
  }
  await userEvent.type(screen.getByLabelText("拒绝理由（可选）"), "暂时不要");
  await userEvent.click(screen.getByRole("button", { name: "拒绝" }));
  await waitFor(() => expect(sent).toContain("暂时不要"));
});
