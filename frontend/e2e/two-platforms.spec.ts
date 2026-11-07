import { expect, test } from "@playwright/test";
import { launch } from "./launch";

// 脚本模型："两个平台"开头起草 B 站加小红书的计划，带"风控"时 B 站分段打开第一条就风控。
test("一个平台风控暂停，另一个平台照常完成", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  async function send(text: string) {
    await page.getByPlaceholder("给 Agent 发消息…").fill(text);
    await page.getByRole("button", { name: "发送消息" }).click();
  }
  await send("两个平台风控测试");
  const summary = page.getByRole("region", { name: "计划摘要" });
  await expect(summary).toBeVisible();
  await expect(summary.getByText("B 站", { exact: false }).first()).toBeVisible();
  await expect(summary.getByText("小红书", { exact: false }).first()).toBeVisible();
  await send("开始");
  await page
    .getByRole("region", { name: "采集审批" })
    .getByRole("button", { name: "批准" })
    .click();
  const progress = page.getByRole("region", { name: "采集进度" });
  const bili = progress.getByRole("region", { name: "B 站采集任务" });
  const xhs = progress.getByRole("region", { name: "小红书采集任务" });
  await expect(bili.getByText(/风控暂停/)).toBeVisible({ timeout: 30000 });
  await expect(bili.getByRole("button", { name: "已验证，继续（冷却后恢复）" })).toBeVisible();
  await expect(bili.getByRole("button", { name: "跳过剩余部分" })).toBeVisible();
  await expect(
    page
      .getByRole("complementary")
      .first()
      .getByText(/冷却中/),
  ).toBeVisible();
  await expect(xhs.getByText("小红书 · 已完成")).toBeVisible({ timeout: 30000 });
  await expect(xhs.getByText(/实得 \/ 计划：3 \/ 3/)).toBeVisible();
  await expect(xhs.getByText(/字幕/)).toHaveCount(0);

  await page.getByRole("link", { name: "所有数据集" }).click();
  const card = page.getByRole("article").filter({ hasText: "风控测试数据集" });
  await expect(card.getByText(/小红书 3 条/)).toBeVisible();
  await card.getByRole("button", { name: "打开" }).click();
  const dataset = page.getByRole("region", { name: "数据集内容" });
  await dataset.getByLabel("平台").selectOption("xhs");
  await expect(dataset.locator("tbody tr")).toHaveCount(3);
  // 打开小红书笔记要带 xsec_token，链接由后端拼好（open_url）。
  await expect(
    dataset.locator("tbody a[href*='xiaohongshu.com/explore/']").first(),
  ).toHaveAttribute("href", /xsec_token=/);
});
