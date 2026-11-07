import { expect, test } from "@playwright/test";
import { launch } from "./launch";

test("没流出内容就用尽时只有额度卡片", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await page.getByPlaceholder("给 Agent 发消息…").fill("额度立刻用尽的一轮");
  await page.getByRole("button", { name: "发送消息" }).click();
  const card = page.getByRole("alert").filter({ hasText: "额度" });
  await expect(card).toBeVisible();
  await expect(card.getByRole("link", { name: "Manage usage" })).toBeVisible();
  await expect(page.getByText("未完成", { exact: true })).toBeHidden();
});

test("有工具调用的对话里失败，错误卡片不被重挂清掉", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await page.getByPlaceholder("给 Agent 发消息…").fill("采集咖啡");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("已起草计划，请在卡片上检查后确认。")).toBeVisible();
  await page.waitForTimeout(500);
  await page.getByPlaceholder("给 Agent 发消息…").fill("额度立刻用尽");
  await page.getByRole("button", { name: "发送消息" }).click();
  const card = page.getByRole("alert").filter({ hasText: "额度" });
  await expect(card).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(card).toBeVisible();
});

test("额度用尽时显示额度卡片，换模型后重试", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await page.getByPlaceholder("给 Agent 发消息…").fill("额度用尽的一轮");
  await page.getByRole("button", { name: "发送消息" }).click();

  const card = page.getByRole("alert").filter({ hasText: "额度" });
  await expect(card).toBeVisible();
  await expect(page.getByText("已写出的一半")).toBeVisible();
  await expect(page.getByText("未完成", { exact: true })).toBeVisible();
  await expect(card.getByRole("link", { name: "Manage usage" })).toHaveAttribute(
    "href",
    "https://chatgpt.com/settings/usage",
  );
  // 绝不自动切换：用户点之前，当前模型不变
  await expect(page.getByRole("button", { name: /^模型：.*e2e-model/ })).toBeVisible();

  await card.getByRole("button", { name: "换成 备用配置 并重试" }).click();
  await expect(page.getByText("备用模型的回复")).toBeVisible();
  await expect(card).toBeHidden();
  await expect(page.getByRole("button", { name: /^模型：.*e2e-backup/ })).toBeVisible();
  // 重试不重复用户消息
  await page.reload();
  await expect(page.getByText("备用模型的回复")).toBeVisible();
  await expect(page.getByRole("main").getByText("额度用尽的一轮", { exact: true })).toHaveCount(1);
});

// 放在最后：上一条用例已切到备用模型，这一条会把它标为不可用。
test("已有历史的对话里凭证失效，错误卡片留在消息下面", async ({ page }) => {
  await launch(page);
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await page.getByPlaceholder("给 Agent 发消息…").fill("你好");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("备用模型的回复")).toBeVisible();
  await page.getByPlaceholder("给 Agent 发消息…").fill("凭证失效");
  await page.getByRole("button", { name: "发送消息" }).click();
  const card = page.getByRole("alert").filter({ hasText: "模型凭证无效" });
  await expect(card).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(card).toBeVisible();
  // 模型不可用时输入框禁用，但卡片上的按钮要能点
  await card.getByRole("button", { name: "去设置" }).click();
  await expect(page.getByRole("dialog", { name: "设置" })).toBeVisible();
});
