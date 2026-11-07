import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { pickOption } from "@/test/select";
import { server } from "@/test/server";
import { ExportButton } from "./ExportButton";

test("显示筛选条数并生成带选项的下载链接", async () => {
  server.use(
    http.get("*/api/datasets/7/contents", ({ request }) => {
      const params = new URL(request.url).searchParams;
      expect(params.get("keyword")).toBe("咖啡");
      expect(params.get("limit")).toBe("1");
      return HttpResponse.json({ total: 9, filtered_total: 3, items: [] });
    }),
  );
  const user = userEvent.setup();
  render(<ExportButton datasetId={7} filter={{ keyword: "咖啡" }} sort="likes_desc" />);
  await user.click(screen.getByRole("button", { name: "导出" }));
  expect(await screen.findByText("按当前筛选导出 3 条")).toBeInTheDocument();
  await pickOption(user, "格式", "Markdown");
  await user.click(screen.getByLabelText("包含字幕全文"));
  const link = screen.getByRole("link", { name: "确定下载" });
  const url = new URL(link.getAttribute("href")!, "http://localhost");
  expect(url.searchParams.get("keyword")).toBe("咖啡");
  expect(url.searchParams.get("sort")).toBe("likes_desc");
  expect(url.searchParams.get("include_subtitles")).toBe("true");
});
