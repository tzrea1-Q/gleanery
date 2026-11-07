import { defineConfig } from "@playwright/test";

// 每个后端一份临时数据目录，各组用例互不影响：
// collect.spec 会让 B 站风控冷却；platform.spec 会把限速恢复成默认（任务间隔 10 分钟）；
// chat.spec 要看首次启动的使用声明；dataset、export 两个用例要在零间隔下采集；report.spec 单独一组；
// two-platforms.spec 也会让 B 站风控冷却。
function server(port: number) {
  return {
    command: `data_dir=$(mktemp -d); trap 'rm -rf "$data_dir"' EXIT; cd ../backend; uv run --frozen python -m tests.e2e.serve --port ${port} --data-dir "$data_dir" --token e2e-token`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
  };
}

export default defineConfig({
  testDir: "./e2e",
  use: {
    browserName: "chromium",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chat", testMatch: "chat.spec.ts", use: { baseURL: "http://127.0.0.1:8799" } },
    { name: "collect", testMatch: "collect.spec.ts", use: { baseURL: "http://127.0.0.1:8800" } },
    { name: "platform", testMatch: "platform.spec.ts", use: { baseURL: "http://127.0.0.1:8801" } },
    {
      name: "data",
      testMatch: ["dataset.spec.ts", "export.spec.ts"],
      use: { baseURL: "http://127.0.0.1:8802" },
    },
    {
      name: "follow-up",
      testMatch: "follow-up.spec.ts",
      use: { baseURL: "http://127.0.0.1:8804" },
    },
    { name: "report", testMatch: "report.spec.ts", use: { baseURL: "http://127.0.0.1:8803" } },
    {
      name: "two-platforms",
      testMatch: "two-platforms.spec.ts",
      use: { baseURL: "http://127.0.0.1:8805" },
    },
    { name: "quota", testMatch: "quota.spec.ts", use: { baseURL: "http://127.0.0.1:8806" } },
  ],
  webServer: [
    server(8799),
    server(8800),
    server(8801),
    server(8802),
    server(8803),
    server(8804),
    server(8805),
    server(8806),
  ],
});
