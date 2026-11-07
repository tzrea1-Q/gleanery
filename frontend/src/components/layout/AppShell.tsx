import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { DisclaimerDialog } from "@/components/model/DisclaimerDialog";
import { ChatgptNoticeDialog } from "@/components/model/ChatgptNoticeDialog";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useAppState, useConversations, useCreateConversation } from "@/api/queries";
import { useUiStore } from "@/stores/ui";
import { Button } from "@/components/ui/button";
import { PlatformPanel } from "@/components/platform/PlatformPanel";
import { Workspace } from "@/components/workspace/Workspace";
import { useWorkspace } from "@/stores/workspace";

export function NewConversationButton() {
  const create = useCreateConversation();
  const navigate = useNavigate();
  return (
    <div>
      <Button
        disabled={create.isPending}
        onClick={() =>
          create.mutate(undefined, {
            onSuccess: (conversation) =>
              void navigate({
                to: "/c/$conversationId",
                params: { conversationId: String(conversation.id) },
              }),
          })
        }
      >
        新对话
      </Button>
      {create.isError && <p role="alert">新建对话失败，请重试</p>}
    </div>
  );
}

function Sidebar() {
  const conversations = useConversations();
  const appState = useAppState();
  const openSettings = useUiStore((state) => state.openSettings);
  const path = useRouterState({ select: (state) => state.location.pathname });
  return (
    <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto border-r bg-muted/30 p-5">
      <Link to="/" className="text-xl font-semibold">
        Gleanery
      </Link>
      <NewConversationButton />
      {/* 列表项不收缩，放不下时列表自己滚动；min-h 保证窗口矮时也能露出几条 */}
      <nav aria-label="对话列表" className="flex min-h-32 flex-1 flex-col gap-1 overflow-y-auto">
        <h2 className="mb-2 shrink-0 text-sm text-muted-foreground">对话</h2>
        {conversations.isError && <p role="alert">无法加载对话列表</p>}
        {conversations.data?.map((item) => (
          <Link
            key={item.id}
            to="/c/$conversationId"
            params={{ conversationId: String(item.id) }}
            aria-current={path === `/c/${item.id}` ? "page" : undefined}
            title={item.title || "新对话"}
            className="shrink-0 truncate rounded-md px-3 py-2 text-sm aria-[current=page]:bg-accent"
          >
            {item.title || "新对话"}
          </Link>
        ))}
      </nav>
      <Link
        to="/datasets"
        aria-current={path === "/datasets" ? "page" : undefined}
        className="rounded-md px-3 py-2 text-sm aria-[current=page]:bg-accent"
      >
        所有数据集
      </Link>
      <Link
        to="/reports"
        aria-current={path === "/reports" ? "page" : undefined}
        className="rounded-md px-3 py-2 text-sm aria-[current=page]:bg-accent"
      >
        所有报告
      </Link>
      <div className="space-y-3 border-t pt-4 text-sm text-muted-foreground">
        <PlatformPanel />
        <button
          type="button"
          onClick={() => openSettings("models")}
          className="w-full rounded-md border p-2 text-left text-foreground hover:bg-accent"
        >
          {appState.data?.current_model ? (
            <span
              className={
                appState.data.current_model.status === "needs_reconnect"
                  ? "text-destructive"
                  : undefined
              }
            >
              模型：{appState.data.current_model.config_name} · {appState.data.current_model.model}{" "}
              ·{" "}
              {appState.data.current_model.status === "ok"
                ? "正常"
                : appState.data.current_model.status === "needs_reconnect"
                  ? "需要重新连接"
                  : "不可用"}
            </span>
          ) : (
            "模型：未选择模型"
          )}
        </button>
        {appState.isError && <p role="alert">无法加载模型状态</p>}
      </div>
    </aside>
  );
}

export function AppShell() {
  const expired = useUiStore((state) => state.sessionExpired);
  const wide = useWorkspace((state) => state.wide);
  if (expired)
    return (
      <main className="flex min-h-screen items-center justify-center p-6 text-center">
        会话已失效，请重新运行 gleanery 打开应用
      </main>
    );
  return (
    <div
      className={`grid min-h-screen grid-cols-1 md:h-screen ${
        wide
          ? "md:grid-cols-[220px_minmax(0,1fr)_minmax(480px,45%)]"
          : "md:grid-cols-[220px_minmax(0,1fr)_280px]"
      }`}
    >
      <SettingsDialog />
      <DisclaimerDialog />
      <ChatgptNoticeDialog />
      <Sidebar />
      <main className="min-h-[400px] min-w-0 overflow-hidden">
        <Outlet />
      </main>
      <Workspace />
    </div>
  );
}
