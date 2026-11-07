import { QueryClient } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useGlobalEvents } from "./events";

class FakeEventSource extends EventTarget {
  static instance: FakeEventSource;
  onopen: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    super();
    FakeEventSource.instance = this;
  }
}

afterEach(() => vi.unstubAllGlobals());

test("事件使对应查询失效，重连使所有查询失效", () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { unmount } = renderHook(() => useGlobalEvents(client));
  const source = FakeEventSource.instance;
  expect(source.url).toBe("/api/events");
  source.onopen?.();
  expect(invalidate).not.toHaveBeenCalled();
  const cases = [
    ["conversation.updated", [["conversations"], ["conversation", 42]]],
    ["conversation.deleted", [["conversations"]]],
    ["model_configs.changed", [["model-configs"], ["app-state"]]],
    ["app_state.changed", [["app-state"]]],
  ] as const;
  for (const [type, keys] of cases) {
    invalidate.mockClear();
    source.dispatchEvent(new MessageEvent(type, { data: JSON.stringify({ conversation_id: 42 }) }));
    expect(invalidate.mock.calls.map(([options]) => options?.queryKey)).toEqual(keys);
  }
  invalidate.mockClear();
  source.onopen?.();
  expect(invalidate).toHaveBeenCalledWith();
  unmount();
  expect(source.close).toHaveBeenCalledOnce();
});
