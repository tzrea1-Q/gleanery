import { useState } from "react";
import { api } from "@/api/client";
import {
  useAppState,
  useModelConfigs,
  useModelMutation,
  useModelPresets,
  useSetCurrentModel,
  useDisconnectChatgpt,
} from "@/api/queries";
import type { components } from "@/api/schema";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useUiStore } from "@/stores/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { CollectSettings } from "./CollectSettings";
import { DataSettings } from "./DataSettings";

type Config = components["schemas"]["ModelConfigOut"];
type Preset = components["schemas"]["ModelPreset"];
const input = "rounded border p-2";

function ConfigForm({
  config,
  presets,
  done,
  initialPreset,
}: {
  config?: Config;
  presets: Preset[];
  done: () => void;
  initialPreset?: Preset;
}) {
  const [preset, setPreset] = useState(config?.preset ?? initialPreset?.id ?? "");
  const [name, setName] = useState(config?.name ?? initialPreset?.name ?? "");
  const [url, setUrl] = useState(config?.base_url ?? initialPreset?.base_url ?? "");
  const [key, setKey] = useState("");
  const [clear, setClear] = useState(false);
  const save = useModelMutation(async () =>
    config
      ? api.PATCH("/api/model-configs/{config_id}", {
          params: { path: { config_id: config.id } },
          body: { name, base_url: url, ...(clear ? { api_key: "" } : key ? { api_key: key } : {}) },
        })
      : api.POST("/api/model-configs", {
          body: { name, base_url: url, preset, ...(key ? { api_key: key } : {}) },
        }),
  );
  return (
    <form
      className="grid gap-2 rounded border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined, {
          onSuccess: () => {
            setKey("");
            done();
          },
        });
      }}
    >
      {!config && !initialPreset && (
        <label>
          预设
          <select
            className={`${input} block w-full`}
            required
            value={preset}
            onChange={(e) => {
              const p = presets.find((p) => p.id === e.target.value);
              setPreset(e.target.value);
              setName(p?.id === "custom" ? "" : (p?.name ?? ""));
              setUrl(p?.base_url ?? "");
            }}
          >
            <option value="">选择预设</option>
            {presets
              .filter((p) => p.kind !== "anthropic")
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </label>
      )}
      <label>
        名称
        <input
          className={`${input} block w-full`}
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      {preset === "anthropic" ? (
        <details>
          <summary>高级</summary>
          <label>
            Base URL
            <input
              className={`${input} block w-full`}
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
        </details>
      ) : (
        <label>
          Base URL
          <input
            className={`${input} block w-full`}
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
      )}
      <label>
        API Key
        <input
          className={`${input} block w-full`}
          type="password"
          required={!config && !!presets.find((p) => p.id === preset)?.key_required}
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setClear(false);
          }}
          autoComplete="new-password"
        />
      </label>
      {config && (
        <label>
          <input
            type="checkbox"
            checked={clear}
            onChange={(e) => {
              setClear(e.target.checked);
              if (e.target.checked) setKey("");
            }}
          />{" "}
          清除 Key
        </label>
      )}
      <div className="flex gap-2">
        <button className={input} disabled={save.isPending}>
          {save.isPending ? "正在测试连通…" : "保存"}
        </button>
        <button type="button" className={input} onClick={done}>
          取消
        </button>
      </div>
      {save.isError && <p role="alert">保存失败，请重试</p>}
    </form>
  );
}

function ConfigItem({ config, presets }: { config: Config; presets: Preset[] }) {
  const [editing, setEditing] = useState(false);
  const [search, setSearch] = useState("");
  const [manual, setManual] = useState("");
  const [confirm, setConfirm] = useState(false);
  const path = { config_id: config.id };
  const refresh = useModelMutation(() =>
    api.POST("/api/model-configs/{config_id}/refresh-models", { params: { path } }),
  );
  const add = useModelMutation((model: string) =>
    api.POST("/api/model-configs/{config_id}/favorites", { params: { path }, body: { model } }),
  );
  const remove = useModelMutation((model: string) =>
    api.DELETE("/api/model-configs/{config_id}/favorites/{model}", {
      params: { path: { ...path, model } },
    }),
  );
  const test = useModelMutation((model: string) =>
    api.POST("/api/model-configs/{config_id}/favorites/{model}/test", {
      params: { path: { ...path, model } },
    }),
  );
  const del = useModelMutation(() =>
    api.DELETE("/api/model-configs/{config_id}", { params: { path } }),
  );
  const current = useSetCurrentModel();
  const disconnect = useDisconnectChatgpt();
  const chatgpt = config.kind === "chatgpt_plan";
  const names =
    config.available_models?.filter((m) => m.toLowerCase().includes(search.toLowerCase())) ?? [];
  return (
    <section className="space-y-2 rounded border p-3">
      <h3 className="font-semibold">{config.name}</h3>
      {!chatgpt && <p className="break-all text-sm">{config.base_url}</p>}
      <p>
        {config.status === "ok"
          ? "正常"
          : config.status === "needs_reconnect"
            ? `需要重新连接${config.status_reason ? `：${config.status_reason}` : ""}`
            : `不可用：${config.status_reason ?? "未知原因"}`}
      </p>
      {chatgpt ? (
        config.status === "needs_reconnect" ? (
          <a className={input} href="/api/chatgpt/connect" target="_blank" rel="noopener">
            重新连接
          </a>
        ) : (
          <button
            className={input}
            disabled={disconnect.isPending}
            onClick={() => disconnect.mutate()}
          >
            断开连接
          </button>
        )
      ) : editing ? (
        <ConfigForm config={config} presets={presets} done={() => setEditing(false)} />
      ) : (
        <button className={input} onClick={() => setEditing(true)}>
          编辑
        </button>
      )}{" "}
      <button className={input} onClick={() => setConfirm(true)}>
        删除
      </button>
      {confirm && (
        <div role="alertdialog" aria-label={`删除 ${config.name}`}>
          <p>
            {chatgpt ? "删除后要重新注册，换账号时才需要这样做。确定删除？" : "确定删除此配置？"}
          </p>
          <button className={input} disabled={del.isPending} onClick={() => del.mutate()}>
            确认删除
          </button>
          <button className={input} onClick={() => setConfirm(false)}>
            取消
          </button>
        </div>
      )}
      <div>
        <button className={input} disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          刷新模型列表
        </button>
      </div>
      <h4 className="font-medium">常用模型</h4>
      {config.favorites.map((f) => (
        <div key={f.name} className="flex flex-wrap items-center gap-2">
          <span>
            {config.model_labels?.[f.name] ?? f.name} ·{" "}
            {f.tool_test === "ok"
              ? "通过"
              : f.tool_test === "untested"
                ? "未测"
                : `不支持工具调用：${f.tool_test_error ?? "未知原因"}`}
          </span>
          <button className={input} disabled={test.isPending} onClick={() => test.mutate(f.name)}>
            重测
          </button>
          <button
            className={input}
            disabled={remove.isPending}
            onClick={() => remove.mutate(f.name)}
          >
            取消勾选
          </button>
          <button
            className={input}
            disabled={config.status !== "ok" || f.tool_test !== "ok" || current.isPending}
            onClick={() => current.mutate({ config_id: config.id, model: f.name })}
          >
            设为当前模型
          </button>
        </div>
      ))}
      {config.available_models === null ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (manual.trim()) add.mutate(manual.trim(), { onSuccess: () => setManual("") });
          }}
        >
          <label>
            手填模型名
            <input className={input} value={manual} onChange={(e) => setManual(e.target.value)} />
          </label>
          <button className={input} disabled={!manual.trim() || add.isPending}>
            添加常用模型
          </button>
        </form>
      ) : (
        <div>
          <label>
            搜索模型
            <input
              className={`${input} block w-full`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <div className="max-h-40 overflow-auto">
            {names.map((m) => (
              <label key={m} className="block">
                <input
                  type="checkbox"
                  checked={config.favorites.some((f) => f.name === m)}
                  disabled={add.isPending || remove.isPending}
                  onChange={(e) => (e.target.checked ? add.mutate(m) : remove.mutate(m))}
                />{" "}
                {config.model_labels?.[m] ?? m}
              </label>
            ))}
          </div>
        </div>
      )}
      {(add.isPending || test.isPending) && <p>正在测试工具调用…</p>}
      {(refresh.isError ||
        add.isError ||
        remove.isError ||
        test.isError ||
        del.isError ||
        disconnect.isError ||
        current.isError) && <p role="alert">操作失败，请重试</p>}
    </section>
  );
}

export function SettingsDialog() {
  const open = useUiStore((s) => s.settingsOpen);
  const close = useUiStore((s) => s.closeSettings);
  const tab = useUiStore((s) => s.settingsTab);
  const configs = useModelConfigs();
  const presets = useModelPresets();
  const state = useAppState();
  const [adding, setAdding] = useState(false);
  const [addingAnthropic, setAddingAnthropic] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) close();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogTitle>设置</DialogTitle>
        <DialogDescription>管理模型与采集设置。</DialogDescription>
        <Tabs
          value={tab}
          onValueChange={(value) =>
            useUiStore.setState({ settingsTab: value as "models" | "collect" | "data" })
          }
        >
          <TabsList>
            <TabsTrigger value="models">模型</TabsTrigger>
            <TabsTrigger value="collect">采集</TabsTrigger>
            <TabsTrigger value="data">数据</TabsTrigger>
          </TabsList>
          <TabsContent value="models" className="space-y-3">
            <h2 className="font-semibold">模型</h2>
            <div className="flex gap-2">
              <button
                className={input}
                onClick={() => {
                  setAdding(true);
                  setAddingAnthropic(false);
                }}
              >
                OpenAI 兼容
              </button>
              <button
                className={input}
                disabled={!presets.data?.some((p) => p.id === "anthropic")}
                onClick={() => {
                  setAdding(true);
                  setAddingAnthropic(true);
                }}
              >
                Anthropic
              </button>
              {!configs.data?.some((c) => c.kind === "chatgpt_plan") && (
                <a className={input} href="/api/chatgpt/connect" target="_blank" rel="noopener">
                  Continue with ChatGPT
                </a>
              )}
            </div>
            {(configs.isError || presets.isError) && <p role="alert">无法加载模型配置或预设</p>}
            {configs.data?.map((c) => (
              <ConfigItem key={c.id} config={c} presets={presets.data ?? []} />
            ))}
            {adding ? (
              <ConfigForm
                key={addingAnthropic ? "anthropic" : "openai"}
                presets={presets.data ?? []}
                initialPreset={
                  addingAnthropic ? presets.data?.find((p) => p.id === "anthropic") : undefined
                }
                done={() => setAdding(false)}
              />
            ) : (
              <button
                className={input}
                onClick={() => {
                  setAdding(true);
                  setAddingAnthropic(false);
                }}
              >
                添加配置
              </button>
            )}
            {state.data?.credential_backend === "file" && (
              <p role="alert" className="font-semibold text-destructive">
                凭证以明文文件保存在应用数据目录（系统钥匙串不可用）
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              本地数据（数据库、导出文件）不额外加密，依赖系统磁盘加密（FileVault / BitLocker）
            </p>
          </TabsContent>
          <TabsContent value="collect">
            <CollectSettings />
          </TabsContent>
          <TabsContent value="data">
            <DataSettings />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
