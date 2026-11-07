import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { pickOption } from "@/test/select";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { server } from "@/test/server";
import { useUiStore } from "@/stores/ui";
import { SettingsDialog } from "./SettingsDialog";

const config = {
  id: 1,
  name: "OpenAI",
  preset: "openai",
  base_url: "https://example.com",
  api_style: "responses",
  status: "ok",
  status_reason: null,
  has_credential: true,
  available_models: null,
  models_fetched_at: null,
  favorites: [{ name: "broken", tool_test: "failed", tool_test_error: "不支持", tested_at: null }],
  created_at: 1,
  updated_at: 1,
};
test("选择预设、保存配置并显示状态，密钥不回显", async () => {
  let saved = false;
  let submitted: unknown;
  server.use(
    http.get("*/api/model-presets", () =>
      HttpResponse.json([
        {
          id: "openai",
          name: "OpenAI",
          base_url: "https://example.com",
          api_style: "responses",
          key_required: true,
        },
      ]),
    ),
    http.get("*/api/model-configs", () => HttpResponse.json(saved ? [config] : [])),
    http.post("*/api/model-configs", async ({ request }) => {
      submitted = await request.json();
      saved = true;
      return HttpResponse.json(config, { status: 201 });
    }),
  );
  useUiStore.getState().openSettings();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SettingsDialog />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "添加配置" }));
  await pickOption(user, await screen.findByLabelText("预设"), "OpenAI");
  expect(screen.getByLabelText("名称")).toHaveValue("OpenAI");
  expect(screen.getByLabelText("Base URL")).toHaveValue("https://example.com");
  const key = screen.getByLabelText("API Key");
  expect(key).toHaveAttribute("type", "password");
  await user.type(key, "secret");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByText("正常")).toBeInTheDocument();
  expect(submitted).toMatchObject({ api_key: "secret" });
  expect(screen.queryByDisplayValue("secret")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^常用模型/ }));
  expect(screen.getByLabelText("手填模型名")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "设为当前模型" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /的操作$/ }));
  await user.click(await screen.findByRole("menuitem", { name: "编辑" }));
  expect(screen.getByLabelText("API Key")).toHaveValue("");
  await waitFor(() => expect(screen.getByText(/不支持工具调用/)).toBeInTheDocument());
});

test("可以直接打开采集标签", async () => {
  server.use(
    http.get("*/api/model-presets", () => HttpResponse.json([])),
    http.get("*/api/model-configs", () => HttpResponse.json([])),
    http.get("*/api/collect-settings", () =>
      HttpResponse.json({ warmup_enabled: true, platforms: {} }),
    ),
    http.get("*/api/risk-events", () => HttpResponse.json([])),
  );
  useUiStore.getState().openSettings("collect");
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SettingsDialog />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("tab", { name: "采集" })).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByRole("checkbox", { name: "登录后预热" })).toBeChecked();
});

test("Anthropic 表单使用预设并将 Base URL 放入高级设置", async () => {
  server.use(
    http.get("*/api/model-presets", () =>
      HttpResponse.json([
        {
          id: "anthropic",
          kind: "anthropic",
          name: "Anthropic",
          base_url: "https://api.anthropic.com",
          key_required: true,
        },
      ]),
    ),
    http.get("*/api/model-configs", () => HttpResponse.json([])),
  );
  useUiStore.getState().openSettings();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SettingsDialog />
    </QueryClientProvider>,
  );
  await userEvent.click(await screen.findByRole("button", { name: "Anthropic" }));
  expect(screen.getByLabelText("名称")).toHaveValue("Anthropic");
  expect(screen.getByLabelText("API Key")).toHaveAttribute("type", "password");
  expect(screen.getByText("高级")).toBeInTheDocument();
  await userEvent.click(screen.getByText("高级"));
  expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.anthropic.com");
});

test.each(["ok", "needs_reconnect"])("ChatGPT 配置状态 %s 的连接操作", async (status) => {
  let disconnected = false;
  server.use(
    http.get("*/api/model-presets", () => HttpResponse.json([])),
    http.get("*/api/model-configs", () =>
      HttpResponse.json(
        disconnected ? [] : [{ ...config, kind: "chatgpt_plan", status, favorites: [] }],
      ),
    ),
    http.post("*/api/chatgpt/disconnect", () => {
      disconnected = true;
      return HttpResponse.json(config);
    }),
  );
  useUiStore.getState().openSettings();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SettingsDialog />
    </QueryClientProvider>,
  );
  await screen.findByText("OpenAI");
  expect(screen.queryByText("https://example.com")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Continue with ChatGPT" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /的操作$/ }));
  await screen.findByRole("menuitem", { name: "删除" });
  expect(screen.queryByRole("menuitem", { name: "编辑" })).not.toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  if (status === "ok") {
    await userEvent.click(screen.getByRole("button", { name: "断开连接" }));
    await waitFor(() => expect(disconnected).toBe(true));
    expect(await screen.findByRole("link", { name: "Continue with ChatGPT" })).toBeInTheDocument();
  } else {
    expect(screen.getByRole("link", { name: "重新连接" })).toHaveAttribute(
      "href",
      "/api/chatgpt/connect",
    );
  }
});
