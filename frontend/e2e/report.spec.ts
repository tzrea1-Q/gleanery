import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { launch } from "./launch";

test("采集、引用、编辑并导出报告", async ({ page }) => {
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
  await expect(page.getByRole("region", { name: "采集结束" })).toBeVisible({ timeout: 30000 });
  await send("写报告");
  await expect(page.getByRole("region", { name: "报告", exact: true })).toBeVisible();
  await page
    .getByRole("region", { name: "报告", exact: true })
    .getByRole("button", { name: "在工作区打开" })
    .click();
  await page.getByRole("button", { name: "原文", exact: true }).first().click();
  await expect(page.locator('[data-focus-id^="c-"][data-highlighted="true"]')).toBeVisible();
  await page
    .getByRole("navigation", { name: "工作区阶段" })
    .getByRole("button", { name: /^报告/ })
    .click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page
    .getByLabel("Markdown 源码")
    .fill((await page.getByLabel("Markdown 源码").inputValue()) + "\n修改后的报告");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "历史版本" }).click();
  await expect(page.getByText(/第 2 版/)).toBeVisible();
  await page.getByRole("button", { name: "导出", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载 .md" }).click();
  expect(await readFile(await (await download).path(), "utf8")).toContain("[^1]");
});
