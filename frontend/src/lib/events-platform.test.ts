import { QueryClient } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { registerPlatformEvents } from "./events-platform";

test("平台、登录和风控事件刷新对应查询并转交通知", () => {
  const source = new EventTarget();
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  registerPlatformEvents(source as EventSource, client);
  source.dispatchEvent(new MessageEvent("platform.updated", { data: "{}" }));
  source.dispatchEvent(new MessageEvent("login.updated", { data: "{}" }));
  source.dispatchEvent(new MessageEvent("risk_event.created", { data: '{"platform":"bili"}' }));
  expect(invalidate.mock.calls.filter(([arg]) => arg?.queryKey?.[0] === "platforms")).toHaveLength(
    3,
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["risk-events"] });
});
