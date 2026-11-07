import { createFileRoute } from "@tanstack/react-router";
import { NewConversationButton } from "@/components/layout/AppShell";
import { FirstRunSlot } from "@/components/chat/ConversationThread";

export const Route = createFileRoute("/")({
  component: () => (
    <div className="flex h-full flex-col items-center justify-center gap-5 p-6">
      <FirstRunSlot />
      <h1 className="text-4xl font-semibold tracking-tight">开始一段新对话</h1>
      <p className="text-muted-foreground">创建对话，告诉 Agent 你想采集和整理的信息。</p>
      <NewConversationButton />
    </div>
  ),
});
