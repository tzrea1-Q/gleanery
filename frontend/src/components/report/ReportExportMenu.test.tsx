import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { ReportExportMenu } from "./ReportExportMenu";

test("下载和复制使用相同的导出地址", async () => {
  server.use(http.get("*/api/reports/7/export", () => new HttpResponse("# 报告\n[^1]")));
  const user = userEvent.setup();
  const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  render(<ReportExportMenu reportId={7} />);
  await user.click(screen.getByRole("button", { name: "导出" }));
  expect(screen.getByRole("link", { name: "下载 .md" })).toHaveAttribute(
    "href",
    "/api/reports/7/export",
  );
  await user.click(screen.getByRole("button", { name: "复制为 Markdown" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已复制");
  expect(writeText).toHaveBeenCalledWith("# 报告\n[^1]");
});
