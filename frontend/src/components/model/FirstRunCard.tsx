import { useAppState } from "@/api/queries";
import { ChatCard } from "@/components/common/ChatCard";
import { Button } from "@/components/ui/button";
import { useUiStore } from "@/stores/ui";

export function FirstRunCard() {
  const state = useAppState();
  const open = useUiStore((s) => s.openSettings);
  const current = state.data?.current_model;
  if (!state.data) return null;
  if (current?.status === "needs_reconnect")
    return (
      <ChatCard aria-label="需要重新连接" className="mx-auto mt-4 w-full max-w-2xl">
        <h2 className="text-xl font-semibold tracking-tight">需要重新连接</h2>
        <p className="text-muted-foreground">
          {current.config_name} · {current.model}：{current.status_reason ?? "授权已失效"}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <a href="/api/chatgpt/connect" target="_blank" rel="noopener">
              重新连接
            </a>
          </Button>
          <Button variant="outline" onClick={() => open("models")}>
            换个模型
          </Button>
        </div>
      </ChatCard>
    );
  if (current?.status === "unavailable")
    return (
      <ChatCard aria-label="当前模型不可用" className="mx-auto mt-4 w-full max-w-2xl">
        <h2 className="text-xl font-semibold tracking-tight">当前模型不可用</h2>
        <p className="text-muted-foreground">
          {current.config_name} · {current.model}：{current.status_reason ?? "模型配置不可用"}
        </p>
        <Button onClick={() => open("models")}>去设置</Button>
      </ChatCard>
    );
  if (current) return null;
  return (
    <ChatCard aria-label="先选一个模型" className="mx-auto mt-4 w-full max-w-2xl">
      <h2 className="text-xl font-semibold tracking-tight">先选一个模型</h2>
      <p className="text-muted-foreground">配置模型后即可开始对话。</p>
      <div className="flex flex-wrap gap-2">
        {["OpenAI 兼容", "Anthropic", "ChatGPT 套餐"].map((name) => (
          <Button key={name} variant="outline" onClick={() => open("models")}>
            {name}
          </Button>
        ))}
      </div>
    </ChatCard>
  );
}
