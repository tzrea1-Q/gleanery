import { expect, test } from "@playwright/test";
import { launch } from "./launch";

test("平台登录与采集限速设置", async ({ page }) => {
  await launch(page);
  await page.getByRole("link", { name: "平台账号" }).click();
  const platform = page.getByRole("region", { name: "B 站" });
  await expect(platform.getByRole("heading", { name: "B 站 · 正常" })).toBeVisible();
  await platform.getByRole("button", { name: "扫码登录" }).click();
  await expect(platform.getByText(/扫码登录：成功/)).toBeVisible();
  await page.getByRole("button", { name: /^模型：/ }).click();
  const dialog = page.getByRole("dialog", { name: "设置" });
  await dialog.getByRole("tab", { name: "采集" }).click();
  const group = dialog.locator("form").filter({ has: page.getByRole("heading", { name: "B 站" }) });
  await group.getByLabel("页面间隔下界", { exact: true }).fill("1");
  await group.getByRole("button", { name: "保存" }).click();
  await expect(group.getByRole("alert")).toContainText("不能低于 1.5 秒");
  await group.getByRole("button", { name: "恢复默认" }).click();
  await expect(group.getByLabel("页面间隔下界", { exact: true })).toHaveValue("3");
  await expect(group.getByRole("alert")).toHaveCount(0);
});
