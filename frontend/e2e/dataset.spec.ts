import { expect, test } from "@playwright/test";
import { launch } from "./launch";

test("采集后展开并按评论 ID 定位", async ({ page }) => {
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
  await dataset
    .getByRole("button", { name: /展开内容/ })
    .first()
    .click();
  await expect(dataset.getByLabel("正文")).not.toBeEmpty();
  const comment = dataset.locator("[data-focus-id^='m-']").first();
  await expect(comment).toBeVisible();
  const id = /#(\d+)/.exec(await comment.locator("small").innerText())![1];
  await dataset.getByLabel("按 ID 定位").fill(`m:${id}`);
  await dataset.getByRole("button", { name: "定位", exact: true }).click();
  await expect(comment).toHaveAttribute("data-highlighted", "true");
  await expect(comment).toBeVisible();
});
