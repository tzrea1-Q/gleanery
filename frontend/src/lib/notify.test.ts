import { afterEach, expect, test, vi } from "vitest";
import { notifyRisk } from "./notify";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});
test("仅在后台、启用且授权时发通知，点击聚焦", () => {
  const focus = vi.spyOn(window, "focus").mockImplementation(() => {});
  const notifications: { onclick: (() => void) | null }[] = [];
  class FakeNotification {
    static permission = "granted";
    onclick = null;
    constructor(public title: string) {
      notifications.push(this);
    }
  }
  vi.stubGlobal("Notification", FakeNotification);
  const hidden = vi.spyOn(document, "hidden", "get");
  localStorage.setItem("gleanery.notify-risk", "true");
  hidden.mockReturnValue(false);
  notifyRisk("bili");
  expect(notifications).toHaveLength(0);
  hidden.mockReturnValue(true);
  FakeNotification.permission = "denied";
  notifyRisk("bili");
  expect(notifications).toHaveLength(0);
  FakeNotification.permission = "granted";
  notifyRisk("bili");
  expect(notifications).toHaveLength(1);
  notifications[0].onclick?.();
  expect(focus).toHaveBeenCalled();
  hidden.mockRestore();
  focus.mockRestore();
});
