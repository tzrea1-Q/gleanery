import { useAppState } from "@/api/queries";
import { useUiStore } from "@/stores/ui";

export function FirstRunCard() {
  const state = useAppState();
  const open = useUiStore((s) => s.openSettings);
  const current = state.data?.current_model;
  if (!state.data) return null;
  if (current?.status === "needs_reconnect")
    return (
      <section className="rounded-lg border p-5" aria-label="需要重新连接">
        <h2 className="text-lg font-semibold">需要重新连接</h2>
        <p>
          {current.config_name} · {current.model}：{current.status_reason ?? "授权已失效"}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            className="rounded border p-2"
            href="/api/chatgpt/connect"
            target="_blank"
            rel="noopener"
          >
            重新连接
          </a>
          <button className="rounded border p-2" onClick={() => open("models")}>
            换个模型
          </button>
        </div>
      </section>
    );
  if (current?.status === "unavailable")
    return (
      <section className="rounded-lg border p-5" aria-label="当前模型不可用">
        <h2 className="text-lg font-semibold">当前模型不可用</h2>
        <p>
          {current.config_name} · {current.model}：{current.status_reason ?? "模型配置不可用"}
        </p>
        <button className="mt-3 rounded border p-2" onClick={() => open("models")}>
          去设置
        </button>
      </section>
    );
  if (current) return null;
  return (
    <section className="rounded-lg border p-5" aria-label="先选一个模型">
      <h2 className="text-lg font-semibold">先选一个模型</h2>
      <p>配置模型后即可开始对话。</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="rounded border p-2" onClick={() => open("models")}>
          OpenAI 兼容
        </button>
        <button className="rounded border p-2" onClick={() => open("models")}>
          Anthropic
        </button>
        <button className="rounded border p-2" onClick={() => open("models")}>
          ChatGPT 套餐
        </button>
      </div>
    </section>
  );
}
