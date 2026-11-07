import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useWorkspace } from "@/stores/workspace";
import { ReportMarkdown } from "./ReportMarkdown";
import type { components } from "@/api/schema";

type Citation = components["schemas"]["CitationOut"];
const content: Citation = {
  kind: "content",
  target_id: 1,
  content_id: 1,
  platform: "bili",
  excerpt: "<b>摘录</b>",
  author: "作者",
  url: "https://example.com",
  saved_at: 1,
  deleted: false,
};
const comment: Citation = { ...content, kind: "comment", target_id: 2, excerpt: "评论" };

test("安全渲染 GFM 和代码，定位单条引用", async () => {
  let query = "";
  server.use(
    http.get("*/api/locate", ({ request }) => {
      query = new URL(request.url).search;
      return HttpResponse.json({ dataset_id: 7, content_id: 1, comment_id: null });
    }),
  );
  render(
    <ReportMarkdown
      markdown={
        "| 标题 |\n| --- |\n| 值 |\n\n<script>alert(1)</script>\n\n[危险](javascript:alert(1)) `[[c:1]]` [[c:1]]"
      }
      citations={[content]}
      primaryDatasetId={4}
    />,
  );
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText("危险").closest("a")).toBeNull();
  expect(screen.getByText("[[c:1]]")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "原文" }));
  await waitFor(() =>
    expect(useWorkspace.getState().pendingFocus).toEqual({ contentId: 1, datasetId: 7 }),
  );
  expect(query).toContain("prefer_dataset_id=4");
});

test("多条先显示列表，评论定位，删除及无数据集显示快照，缺失引用失效", async () => {
  server.use(
    http.get("*/api/locate", ({ request }) =>
      HttpResponse.json({
        dataset_id: new URL(request.url).searchParams.get("content_id") === "1" ? 7 : null,
      }),
    ),
  );
  const removed = { ...content, target_id: 3, content_id: 3, deleted: true };
  const detached = { ...content, target_id: 4, content_id: 4 };
  render(
    <ReportMarkdown
      markdown="[[c:1, m:2]] [[c:3]] [[c:4]] [[c:9]]"
      citations={[content, comment, removed, detached]}
      primaryDatasetId={null}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "原文 ×2" }));
  expect(screen.getByRole("dialog", { name: "引用列表" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /评论/ }));
  await waitFor(() =>
    expect(useWorkspace.getState().pendingFocus).toEqual({
      contentId: 1,
      commentId: 2,
      datasetId: 7,
    }),
  );
  await user.click(screen.getAllByRole("button", { name: "原文" })[0]);
  expect(screen.getByText("已从内容库删除")).toBeInTheDocument();
  expect(screen.getByText(/<b>摘录<\/b>/)).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await user.click(screen.getAllByRole("button", { name: "原文" })[1]);
  expect(await screen.findByRole("dialog", { name: "引用快照" })).toBeInTheDocument();
  expect(screen.getByTitle("找不到 c:9")).toHaveTextContent("失效引用");
});
