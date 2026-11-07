import { expect, type Page } from "@playwright/test";

// 使用声明要等应用状态加载完才弹出，弹出时其余页面对读屏隐藏；
// 所以等声明或模型按钮二者之一出现，再判断要不要关声明。
export async function launch(page: Page) {
  await page.goto("/auth/launch?token=e2e-token");
  const disclaimer = page.getByRole("dialog", { name: "使用声明" });
  await expect(
    disclaimer.or(page.getByRole("button", { name: /^模型：.*e2e-/ })).first(),
  ).toBeVisible();
  // 同一后端上并行的另一个用例可能先点了"我知道了"，声明随事件关闭，这里的点击就落空。
  if (await disclaimer.isVisible())
    await disclaimer
      .getByRole("button", { name: "我知道了" })
      .click({ timeout: 5000 })
      .catch(() => undefined);
  await expect(disclaimer).toBeHidden();
}
