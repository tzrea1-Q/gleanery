import { expect, test } from "@playwright/test";
import { launch } from "./launch";

test("采集结束后自动整理并显示回复", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  const send = async (text: string) => {
    await page.getByPlaceholder("给 Agent 发消息…").fill(text);
    await page.getByRole("button", { name: "发送消息" }).click();
  };
  await send("采集咖啡并整理成报告");
  await expect(page.getByRole("region", { name: "计划摘要" })).toBeVisible();
  await send("开始");
  await page
    .getByRole("region", { name: "采集审批" })
    .getByRole("button", { name: "批准" })
    .click();
  await expect(page.getByRole("region", { name: "采集事件" }).getByText(/采集结束/)).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByText("已按后续意图整理完毕")).toBeVisible({ timeout: 30000 });
});
