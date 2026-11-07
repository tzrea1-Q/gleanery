import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { launch } from "./launch";

const CHECKS: Record<string, string> = {
  xlsx: "import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert 'xl/workbook.xml' in z.namelist(); assert '内容' in z.read('xl/workbook.xml').decode()",
  csv: "import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert set(z.namelist()) == {'内容.csv','评论.csv','字幕.csv'}; assert all(z.read(n).startswith(b'\\xef\\xbb\\xbf') for n in z.namelist())",
};

test("采集后从工作区下载三种导出", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  async function send(text: string) {
    await page.getByPlaceholder("给 Agent 发消息…").fill(text);
    await page.getByRole("button", { name: "发送消息" }).click();
  }
  await send("采集咖啡");
  await expect(page.getByRole("region", { name: "计划摘要" })).toBeVisible();
  await send("开始");
  await page
    .getByRole("region", { name: "采集审批" })
    .getByRole("button", { name: "批准" })
    .click();
  const finished = page.getByRole("region", { name: "采集结束" });
  await expect(finished).toBeVisible({ timeout: 30000 });
  await finished.getByRole("button", { name: "在工作区查看" }).click();
  const dataset = page.getByRole("region", { name: "数据集内容" });
  await expect(dataset.locator("tbody tr").first()).toBeVisible();
  for (const [format, label, suffix] of [
    ["xlsx", "Excel", ".xlsx"],
    ["csv", "CSV", ".zip"],
    ["md", "Markdown", ".md"],
  ]) {
    await dataset.getByRole("button", { name: "导出", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "导出数据集" });
    await expect(dialog.getByText(/按当前筛选导出 \d+ 条/)).toBeVisible();
    await dialog.getByLabel("格式").click();
    await page.getByRole("option", { name: label }).click();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      dialog.getByText("确定下载").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(new RegExp(`^咖啡数据集-.*\\${suffix}$`));
    const path = await download.path();
    if (format === "md") expect(await readFile(path, "utf-8")).toContain("# 咖啡数据集");
    else execFileSync("python3", ["-c", CHECKS[format], path]);
  }
});
