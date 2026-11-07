import { expect, test, type Page } from "@playwright/test";
import { launch } from "./launch";

async function start(page: Page, text: string) {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await send(page, text);
  await expect(page.getByRole("region", { name: "计划摘要" })).toBeVisible();
}
async function send(page: Page, text: string) {
  await page.getByPlaceholder("给 Agent 发消息…").fill(text);
  await page.getByRole("button", { name: "发送消息" }).click();
}

test("编辑计划、批准采集并查看数据集", async ({ page }) => {
  await start(page, "采集咖啡");
  const workspace = page.getByRole("complementary", { name: "工作区" });
  await workspace.getByRole("spinbutton", { name: "数量" }).fill("2");
  await workspace.getByRole("button", { name: "保存", exact: true }).click();
  await expect(workspace.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await send(page, "开始");
  await page
    .getByRole("region", { name: "采集审批" })
    .getByRole("button", { name: "批准" })
    .click();
  const finished = page.getByRole("region", { name: "采集结束" });
  await expect(finished).toBeVisible({ timeout: 30000 });
  await expect(
    finished.getByRole("region", { name: "数据集预览" }).locator("tbody tr"),
  ).toHaveCount(2);
  await finished.getByRole("button", { name: "在工作区查看" }).click();
  await expect(
    workspace.getByRole("region", { name: "数据集内容" }).locator("tbody tr"),
  ).toHaveCount(2);
});
test("风控暂停显示操作和平台冷却", async ({ page }) => {
  await start(page, "采集风控");
  await send(page, "开始");
  await page
    .getByRole("region", { name: "采集审批" })
    .getByRole("button", { name: "批准" })
    .click();
  const progress = page.getByRole("region", { name: "采集进度" });
  await expect(progress.getByText(/风控暂停/)).toBeVisible({ timeout: 30000 });
  await expect(progress.getByRole("button", { name: "已验证，继续（冷却后恢复）" })).toBeVisible();
  await expect(progress.getByRole("button", { name: "跳过剩余部分" })).toBeVisible();
  await expect(
    page
      .getByRole("complementary")
      .first()
      .getByText(/冷却中/),
  ).toBeVisible();
});
