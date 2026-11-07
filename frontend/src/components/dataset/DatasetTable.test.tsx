import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { content } from "@/components/collect/test-data";
import { useWorkspace } from "@/stores/workspace";
import { server } from "@/test/server";
import { DatasetTable } from "./DatasetTable";
import { ConfirmHost } from "@/components/common/ConfirmHost";

test("清除阻挡定位的筛选并高亮评论，移出前显示影响", async () => {
  Element.prototype.scrollIntoView = vi.fn();
  let removed = false;
  server.use(
    http.get("*/api/datasets/2/contents", () =>
      HttpResponse.json({ total: 1, filtered_total: 1, items: [content] }),
    ),
    http.get("*/api/locate", () =>
      HttpResponse.json({ dataset_id: 2, content_id: content.id, comment_id: 9 }),
    ),
    http.get("*/api/datasets/2/contents/locate", ({ request }) =>
      HttpResponse.json({ offset: new URL(request.url).searchParams.has("keyword") ? null : 0 }),
    ),
    http.get("*/api/comments/9/locate", () =>
      HttpResponse.json({ content_id: content.id, root_comment_id: 9, offset: 0 }),
    ),
    http.get("*/api/contents/:id", () =>
      HttpResponse.json({ body: "<b>正文</b>", tags: [], subtitles: [] }),
    ),
    http.get("*/api/contents/:id/comments", () =>
      HttpResponse.json({
        total: 1,
        replies_total: 0,
        items: [{ id: 9, body: "<script>评论</script>", author_nickname: "作者", replies: [] }],
      }),
    ),
    http.post("*/api/datasets/2/remove-impact", () =>
      HttpResponse.json({ removed: 1, not_member: [], recycled_contents: 1, recycled_comments: 2 }),
    ),
    http.post("*/api/datasets/2/remove", () => {
      removed = true;
      return HttpResponse.json({
        removed: 1,
        not_member: [],
        recycled_contents: 1,
        recycled_comments: 2,
      });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DatasetTable id={2} />
      <ConfirmHost />
    </QueryClientProvider>,
  );
  await screen.findByText(content.title!);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("关键词"), "阻挡");
  await user.type(screen.getByLabelText("按 ID 定位"), "m:9");
  await user.click(screen.getByRole("button", { name: /^定位$/ }));
  const comment = await screen.findByText("<script>评论</script>");
  expect(comment.parentElement).toHaveAttribute("data-highlighted", "true");
  expect(screen.getByLabelText("关键词")).toHaveValue("");
  expect(screen.getByText("<b>正文</b>")).toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: `选择内容 ${content.id}` }));
  await user.click(screen.getByRole("button", { name: "移出数据集" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent("回收 1 条内容和 2 条评论");
  await user.click(within(dialog).getByRole("button", { name: "确认移出" }));
  await waitFor(() => expect(removed).toBe(true));
  useWorkspace.setState({ pendingFocus: null, datasetId: null });
});

test("小红书行的字幕列显示 —", async () => {
  server.use(
    http.get("*/api/datasets/3/contents", () =>
      HttpResponse.json({
        total: 2,
        filtered_total: 2,
        items: [
          { ...content, subtitles: 2 },
          { ...content, id: content.id + 1, platform: "xhs", title: "小红书笔记", subtitles: 0 },
        ],
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DatasetTable id={3} />
    </QueryClientProvider>,
  );
  const subtitles = (title: string) =>
    within(screen.getByRole("row", { name: new RegExp(title) })).getAllByRole("cell")[6];
  await screen.findByText("小红书笔记");
  expect(subtitles("小红书笔记")).toHaveTextContent("—");
  expect(subtitles(content.title!)).toHaveTextContent("2");
});
