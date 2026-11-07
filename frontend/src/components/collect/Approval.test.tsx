import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { server } from "@/test/server";

test("审批后自动发送最后一条 assistant 消息", async () => {
  let sent:
    | {
        messages: { role: string; parts: { state?: string; approval?: { approved: boolean } }[] }[];
      }
    | undefined;
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
                type: "tool-start_collection",
                toolCallId: "call-1",
                state: "approval-requested",
                input: { plan_id: 1 },
                approval: { id: "approval-1" },
              },
            ],
          },
        ],
      }),
    ),
    http.get("*/api/plans/1", () =>
      HttpResponse.json({
        id: 1,
        conversation_id: 1,
        status: "draft",
        version: 1,
        body: { title: "咖啡", sections: [] },
        issues: [],
        estimate_seconds: {},
        task_ids: [],
        confirmed_at: null,
        created_at: 1,
        updated_at: 1,
      }),
    ),
    http.get("*/api/tasks", () => HttpResponse.json([])),
    http.post("*/api/chat", async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return new HttpResponse(
        'data: {"type":"start"}\n\ndata: {"type":"start-step"}\n\ndata: {"type":"text-start","id":"t"}\n\ndata: {"type":"text-delta","id":"t","delta":"已开始"}\n\ndata: {"type":"text-end","id":"t"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
        {
          headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
        },
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
  await userEvent.click(await screen.findByRole("button", { name: "批准" }));
  await waitFor(() => expect(sent).toBeDefined());
  expect(sent?.messages).toHaveLength(1);
  expect(sent?.messages[0].role).toBe("assistant");
  expect(sent?.messages[0].parts[0]).toMatchObject({
    state: "approval-responded",
    approval: { approved: true },
  });
});
