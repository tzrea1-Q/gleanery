import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationThread } from "@/components/chat/ConversationThread";
import { server } from "@/test/server";

test("导出卡片写明格式、文件名并给下载按钮", async () => {
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
                type: "tool-export_dataset",
                toolCallId: "call-1",
                state: "output-available",
                input: { dataset_id: 10, format: "xlsx" },
                output: {
                  dataset_id: 10,
                  format: "xlsx",
                  filename: "露营TOP3.xlsx",
                  download_url: "/api/datasets/10/export?format=xlsx",
                  contents: 3,
                  comments: 54,
                  subtitles: 3,
                },
              },
            ],
          },
        ],
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
  const card = await screen.findByRole("region", { name: "数据集导出" });
  expect(card).toHaveTextContent("已导出 Excel");
  expect(card).toHaveTextContent("内容 3 条，评论 54 条，字幕 3 条");
  const link = screen.getByRole("link", { name: "下载 露营TOP3.xlsx" });
  expect(link).toHaveAttribute("href", "/api/datasets/10/export?format=xlsx");
});
