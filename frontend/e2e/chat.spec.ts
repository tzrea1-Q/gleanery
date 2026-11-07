import { expect, test } from "@playwright/test";

test("首次启动、对话和刷新后恢复", async ({ page }) => {
  const message = "请帮我整理这条测试消息，用来确认对话标题会按前面三十个字符截取。";
  await page.goto("/auth/launch?token=e2e-token");
  const disclaimer = page.getByRole("dialog", { name: "使用声明" });
  await expect(disclaimer).toBeVisible();
  await disclaimer.getByRole("button", { name: "我知道了" }).click();
  await expect(disclaimer).toBeHidden();
  await page.getByRole("complementary").first().getByRole("button", { name: "新对话" }).click();
  await page.getByPlaceholder("给 Agent 发消息…").fill(message);
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText(`收到：${message}`, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "对话列表" }).getByText(message.slice(0, 30)),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText(message, { exact: true })).toBeVisible();
  await expect(page.getByText(`收到：${message}`, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "对话列表" }).getByText(message.slice(0, 30)),
  ).toBeVisible();
  await page.reload();
  await expect(disclaimer).toBeHidden();
});
