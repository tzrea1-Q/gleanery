import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";
import { server } from "./server";
import { useUiStore } from "@/stores/ui";

const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === "string" && input.startsWith("/")
        ? new URL(input, window.location.origin)
        : input,
      init,
    );
  }
};
// 测试文件并行跑时渲染偶尔超过默认的 1 秒，findBy 等异步查询放宽到 5 秒。
configure({ asyncUtilTimeout: 5000 });
server.listen();
window.scrollTo = () => {};
// jsdom 没有这些 API，Sidebar 的窗口判断和 Radix 的 Select 都要用到。
window.matchMedia = (query) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList;
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => {};
Element.prototype.releasePointerCapture = () => {};
Element.prototype.scrollIntoView = () => {};
afterEach(() => {
  cleanup();
  server.resetHandlers();
  useUiStore.setState({ settingsOpen: false, settingsTab: "models", sessionExpired: false });
});
afterAll(() => server.close());
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
