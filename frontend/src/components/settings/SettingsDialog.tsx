import { useState } from "react";
import { ChevronDown, MoreHorizontal, Plus } from "lucide-react";
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
import { CheckRow } from "@/components/common/CheckRow";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { StatusBadge, type StatusTone } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from "@/components/ui/item";
import { askConfirm } from "@/stores/confirm";
import { useUiStore } from "@/stores/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { CollectSettings } from "./CollectSettings";
import { DataSettings } from "./DataSettings";

type Config = components["schemas"]["ModelConfigOut"];
type Preset = components["schemas"]["ModelPreset"];

const statusTones: Record<string, StatusTone> = { ok: "success", needs_reconnect: "warning" };
const statusLabels: Record<string, string> = { ok: "正常", needs_reconnect: "需要重新连接" };

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
  const baseUrl = (
    <FormRow label="Base URL">
      <Input required value={url} onChange={(e) => setUrl(e.target.value)} />
    </FormRow>
  );
  return (
    <form
      className="space-y-2 rounded-2xl bg-muted/60 p-4 dark:bg-muted/40"
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
        <FormRow label="预设">
          <FormSelect
            placeholder="选择预设"
            value={preset}
            onValueChange={(value) => {
              const p = presets.find((p) => p.id === value);
              setPreset(value);
              setName(p?.id === "custom" ? "" : (p?.name ?? ""));
              setUrl(p?.base_url ?? "");
            }}
            options={presets
              .filter((p) => p.kind !== "anthropic")
              .map((p) => ({ value: p.id, label: p.name }))}
          />
        </FormRow>
      )}
      <FormRow label="名称">
        <Input required value={name} onChange={(e) => setName(e.target.value)} />
      </FormRow>
      {preset === "anthropic" ? (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="group/advanced -ml-2">
              <ChevronDown className="transition-transform group-data-[state=closed]/advanced:-rotate-90" />
              高级
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">{baseUrl}</CollapsibleContent>
        </Collapsible>
      ) : (
        baseUrl
      )}
      <FormRow label="API Key">
        <Input
          type="password"
          required={!config && !!presets.find((p) => p.id === preset)?.key_required}
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setClear(false);
          }}
          autoComplete="new-password"
        />
      </FormRow>
      {config && (
        <CheckRow
          label="清除 Key"
          checked={clear}
          onCheckedChange={(checked) => {
            setClear(checked);
            if (checked) setKey("");
          }}
        />
      )}
      {save.isError && <Notice>保存失败，请重试</Notice>}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="outline" onClick={done}>
          取消
        </Button>
        <Button type="submit" disabled={save.isPending || (!preset && !config)}>
          {save.isPending ? "正在测试连通…" : "保存"}
        </Button>
      </div>
    </form>
  );
}

function ConfigItem({ config, presets }: { config: Config; presets: Preset[] }) {
  const [editing, setEditing] = useState(false);
  const [search, setSearch] = useState("");
  const [manual, setManual] = useState("");
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
    <section className="space-y-2 rounded-2xl bg-muted/60 p-4 dark:bg-muted/40">
      <Item className="border-0 p-0">
        <ItemContent className="min-w-0">
          <ItemTitle className="max-w-full">
            <h3 className="truncate font-semibold">{config.name}</h3>
            <StatusBadge tone={statusTones[config.status] ?? "danger"}>
              {statusLabels[config.status] ?? "不可用"}
            </StatusBadge>
          </ItemTitle>
          {!chatgpt && <ItemDescription className="break-all">{config.base_url}</ItemDescription>}
          {config.status !== "ok" &&
            (config.status_reason || config.status !== "needs_reconnect") && (
              <ItemDescription>{config.status_reason ?? "未知原因"}</ItemDescription>
            )}
        </ItemContent>
        <ItemActions>
          {chatgpt &&
            (config.status === "needs_reconnect" ? (
              <Button asChild variant="outline" size="sm">
                <a href="/api/chatgpt/connect" target="_blank" rel="noopener">
                  重新连接
                </a>
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={disconnect.isPending}
                onClick={() => disconnect.mutate()}
              >
                断开连接
              </Button>
            ))}
          {/* 非模态：删除项要弹确认框，模态菜单收起时会把 body 的 pointer-events 留在 none。 */}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`${config.name} 的操作`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {!chatgpt && (
                <DropdownMenuItem onSelect={() => setEditing(true)}>编辑</DropdownMenuItem>
              )}
              <DropdownMenuItem disabled={refresh.isPending} onSelect={() => refresh.mutate()}>
                刷新模型列表
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                disabled={del.isPending}
                onSelect={async () => {
                  const confirmed = await askConfirm({
                    title: `删除 ${config.name}`,
                    description: chatgpt
                      ? "删除后要重新注册，换账号时才需要这样做。"
                      : "删除后要重新填写这份配置。",
                    confirmLabel: "确认删除",
                    destructive: true,
                  });
                  if (confirmed) del.mutate();
                }}
              >
                删除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </ItemActions>
      </Item>
      {editing && <ConfigForm config={config} presets={presets} done={() => setEditing(false)} />}
      <Collapsible defaultOpen={config.favorites.length === 0}>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="group/models -ml-2">
            <ChevronDown className="transition-transform group-data-[state=closed]/models:-rotate-90" />
            常用模型
            <span className="font-normal text-muted-foreground tabular-nums">
              {config.favorites.length}
            </span>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-3">
          {config.favorites.length > 0 && (
            <div className="space-y-1.5">
              {config.favorites.map((f) => (
                <div
                  key={f.name}
                  className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-card px-3 py-2"
                >
                  <div className="min-w-0 flex-1 basis-48">
                    <p className="flex items-center gap-2">
                      <span className="truncate">{config.model_labels?.[f.name] ?? f.name}</span>
                      <StatusBadge
                        tone={
                          f.tool_test === "ok"
                            ? "success"
                            : f.tool_test === "untested"
                              ? "neutral"
                              : "danger"
                        }
                      >
                        {f.tool_test === "ok"
                          ? "通过"
                          : f.tool_test === "untested"
                            ? "未测"
                            : "未通过"}
                      </StatusBadge>
                    </p>
                    {f.tool_test !== "ok" && f.tool_test !== "untested" && (
                      <p className="text-xs text-muted-foreground">
                        不支持工具调用：{f.tool_test_error ?? "未知原因"}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={test.isPending}
                    onClick={() => test.mutate(f.name)}
                  >
                    重测
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(f.name)}
                  >
                    取消勾选
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={config.status !== "ok" || f.tool_test !== "ok" || current.isPending}
                    onClick={() => current.mutate({ config_id: config.id, model: f.name })}
                  >
                    设为当前模型
                  </Button>
                </div>
              ))}
            </div>
          )}
          {config.available_models === null ? (
            <form
              className="flex items-start gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (manual.trim()) add.mutate(manual.trim(), { onSuccess: () => setManual("") });
              }}
            >
              <FormRow label="手填模型名" className="min-w-0 flex-1">
                <Input value={manual} onChange={(e) => setManual(e.target.value)} />
              </FormRow>
              <Button type="submit" variant="outline" disabled={!manual.trim() || add.isPending}>
                添加常用模型
              </Button>
            </form>
          ) : (
            <div className="space-y-2">
              <FormRow label="搜索模型">
                <Input value={search} onChange={(e) => setSearch(e.target.value)} />
              </FormRow>
              <div className="max-h-40 space-y-1.5 overflow-auto rounded-xl bg-card p-3">
                {names.map((m) => (
                  <CheckRow
                    key={m}
                    label={config.model_labels?.[m] ?? m}
                    checked={config.favorites.some((f) => f.name === m)}
                    disabled={add.isPending || remove.isPending}
                    onCheckedChange={(checked) => (checked ? add.mutate(m) : remove.mutate(m))}
                  />
                ))}
              </div>
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>
      {(add.isPending || test.isPending) && (
        <p role="status" className="text-xs text-muted-foreground">
          正在测试工具调用…
        </p>
      )}
      {(refresh.isError ||
        add.isError ||
        remove.isError ||
        test.isError ||
        del.isError ||
        disconnect.isError ||
        current.isError) && <Notice>操作失败，请重试</Notice>}
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
      <DialogContent className="flex h-[min(46rem,90vh)] flex-col sm:max-w-3xl">
        <div className="space-y-1">
          <DialogTitle className="text-xl font-semibold tracking-tight">设置</DialogTitle>
          <DialogDescription>管理模型与采集设置。</DialogDescription>
        </div>
        <Tabs
          className="min-h-0 flex-1"
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
          <TabsContent value="models" className="min-h-0 space-y-3 overflow-y-auto">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold tracking-tight">模型</h2>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setAdding(true);
                    setAddingAnthropic(false);
                  }}
                >
                  OpenAI 兼容
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!presets.data?.some((p) => p.id === "anthropic")}
                  onClick={() => {
                    setAdding(true);
                    setAddingAnthropic(true);
                  }}
                >
                  Anthropic
                </Button>
                {!configs.data?.some((c) => c.kind === "chatgpt_plan") && (
                  <Button asChild variant="outline" size="sm">
                    <a href="/api/chatgpt/connect" target="_blank" rel="noopener">
                      Continue with ChatGPT
                    </a>
                  </Button>
                )}
              </div>
            </div>
            {(configs.isError || presets.isError) && <Notice>无法加载模型配置或预设</Notice>}
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
              <Button
                variant="outline"
                className="w-full border-dashed"
                onClick={() => {
                  setAdding(true);
                  setAddingAnthropic(false);
                }}
              >
                <Plus />
                添加配置
              </Button>
            )}
            {state.data?.credential_backend === "file" && (
              <Notice>凭证以明文文件保存在应用数据目录（系统钥匙串不可用）</Notice>
            )}
            <p className="text-xs text-muted-foreground">
              本地数据（数据库、导出文件）不额外加密，依赖系统磁盘加密（FileVault / BitLocker）
            </p>
          </TabsContent>
          <TabsContent value="collect" className="min-h-0 overflow-y-auto">
            <CollectSettings />
          </TabsContent>
          <TabsContent value="data" className="min-h-0 overflow-y-auto">
            <DataSettings />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
