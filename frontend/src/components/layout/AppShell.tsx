import { useState } from "react";
import {
  Bot,
  Database,
  FileText,
  Monitor,
  Moon,
  PanelRightOpen,
  Plus,
  Sun,
  Wheat,
} from "lucide-react";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useTheme } from "next-themes";
import { useAppState, useConversations, useCreateConversation } from "@/api/queries";
import { usePlans, useTasks } from "@/api/queries-collect";
import { ConfirmHost } from "@/components/common/ConfirmHost";
import { ChatgptNoticeDialog } from "@/components/model/ChatgptNoticeDialog";
import { DisclaimerDialog } from "@/components/model/DisclaimerDialog";
import { PlatformDots, PlatformPanel } from "@/components/platform/PlatformPanel";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { Workspace } from "@/components/workspace/Workspace";
import { WorkspaceResizer } from "@/components/workspace/WorkspaceResizer";
import { useUiStore } from "@/stores/ui";
import { useWorkspace } from "@/stores/workspace";

const sidebarKey = "gleanery.sidebar";

// SidebarProvider 自带的 cookie 要靠服务端渲染读回，这里是纯前端应用，自己存。
function readSidebarOpen() {
  // 窗口不够宽时不采用保存的状态，否则三栏同时展开会把对话栏挤没。
  if (window.innerWidth < 1280) return false;
  try {
    return localStorage.getItem(sidebarKey) !== "false";
  } catch {
    return true;
  }
}

function saveSidebarOpen(open: boolean) {
  try {
    localStorage.setItem(sidebarKey, String(open));
  } catch {
    // 存不下只影响下次启动时的默认状态
  }
}

export function NewConversationButton({ className }: { className?: string }) {
  const create = useCreateConversation();
  const navigate = useNavigate();
  return (
    <div className={className}>
      <Button
        aria-label="新对话"
        className="w-full group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:p-0"
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
        <Plus />
        <span className="group-data-[collapsible=icon]:hidden">新对话</span>
      </Button>
      {create.isError && (
        <p role="alert" className="mt-2 text-destructive">
          新建对话失败，请重试
        </p>
      )}
    </div>
  );
}

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton tooltip="外观">
          <Icon />
          <span>外观</span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start">
        <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
          <DropdownMenuRadioItem value="system">跟随系统</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">浅色</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">深色</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ModelEntry() {
  const appState = useAppState();
  const openSettings = useUiStore((state) => state.openSettings);
  const model = appState.data?.current_model;
  const broken = model && model.status !== "ok";
  return (
    <>
      <SidebarMenuButton
        size="lg"
        tooltip="模型设置"
        className="h-auto py-1.5 group-data-[collapsible=icon]:justify-center"
        onClick={() => openSettings("models")}
      >
        <Bot className={broken ? "text-destructive" : undefined} />
        {model ? (
          <span className="min-w-0 leading-snug group-data-[collapsible=icon]:hidden">
            <span className="block truncate">
              模型：{model.config_name} · {model.model}
            </span>
            <span
              className={broken ? "text-xs text-destructive" : "text-xs text-sidebar-foreground/70"}
            >
              {model.status === "ok"
                ? "正常"
                : model.status === "needs_reconnect"
                  ? "需要重新连接"
                  : "不可用"}
            </span>
          </span>
        ) : (
          <span className="group-data-[collapsible=icon]:hidden">模型：未选择模型</span>
        )}
      </SidebarMenuButton>
      {appState.isError && (
        <p role="alert" className="px-2 text-xs text-destructive">
          无法加载模型状态
        </p>
      )}
    </>
  );
}

function AppSidebar() {
  const conversations = useConversations();
  const path = useRouterState({ select: (state) => state.location.pathname });
  return (
    // 组件渲染的是 div，这里补上语义，左栏才是读屏和测试里的"第一个辅助区域"。
    <Sidebar
      variant="floating"
      collapsible="icon"
      role="complementary"
      aria-label="导航"
      className="p-3 pr-0"
    >
      <SidebarHeader className="gap-3 p-3">
        <div className="flex items-center justify-between group-data-[collapsible=icon]:justify-center">
          <Link
            to="/"
            className="flex items-center gap-2 px-1 text-base font-semibold tracking-tight group-data-[collapsible=icon]:hidden"
          >
            <span className="flex size-7 items-center justify-center rounded-lg bg-lime text-[#16161a]">
              <Wheat className="size-4" />
            </span>
            Gleanery
          </Link>
          <SidebarTrigger aria-label="切换左栏" />
        </div>
        <NewConversationButton />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="group-data-[collapsible=icon]:px-3">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton asChild isActive={path === "/datasets"} tooltip="所有数据集">
                <Link to="/datasets" aria-current={path === "/datasets" ? "page" : undefined}>
                  <Database />
                  <span>所有数据集</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton asChild isActive={path === "/reports"} tooltip="所有报告">
                <Link to="/reports" aria-current={path === "/reports" ? "page" : undefined}>
                  <FileText />
                  <span>所有报告</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
        <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel asChild>
            <h2>对话</h2>
          </SidebarGroupLabel>
          <nav aria-label="对话列表">
            {conversations.isError && (
              <p role="alert" className="px-2 text-destructive">
                无法加载对话列表
              </p>
            )}
            <SidebarMenu>
              {conversations.data?.map((item) => {
                const current = path === `/c/${item.id}`;
                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton asChild isActive={current}>
                      <Link
                        to="/c/$conversationId"
                        params={{ conversationId: String(item.id) }}
                        aria-current={current ? "page" : undefined}
                        title={item.title || "新对话"}
                      >
                        <span>{item.title || "新对话"}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </nav>
        </SidebarGroup>
      </SidebarContent>
      {/* 平台出错时内容会变长，限高后自己滚动，不把对话列表挤没 */}
      <SidebarFooter className="max-h-[55%] overflow-y-auto p-3">
        <PlatformPanel />
        <PlatformDots />
        <SidebarMenu>
          <SidebarMenuItem>
            <ModelEntry />
          </SidebarMenuItem>
          <SidebarMenuItem>
            <ThemeMenu />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}

/** 放在 main 外面：对话标题常和第一条消息同文，放进去读屏会念两遍。 */
function ConversationHeader() {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const id = Number(/^\/c\/(\d+)$/.exec(path)?.[1]);
  const conversations = useConversations();
  const plans = usePlans(id || undefined);
  const tasks = useTasks({ conversation_id: id || undefined });
  if (!id) return null;
  const title = conversations.data?.find((item) => item.id === id)?.title || "新对话";
  const plan = plans.data?.at(-1);
  const current = tasks.data?.filter((task) => task.plan_id === plan?.id) ?? [];
  const processed = current.reduce((sum, task) => sum + task.progress.processed, 0);
  const planned = current.reduce((sum, task) => sum + task.progress.planned, 0);
  return (
    <header className="shrink-0 py-2 pt-3 pr-14 pl-6">
      <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="truncate text-muted-foreground">
        {plan
          ? `${plan.body.title}${current.length ? ` · 已采 ${processed} / ${planned} 条` : ""}`
          : "告诉 Agent 你想采集和整理的信息"}
      </p>
    </header>
  );
}

export function AppShell() {
  const expired = useUiStore((state) => state.sessionExpired);
  const wide = useWorkspace((state) => state.wide);
  const width = useWorkspace((state) => state.widths[state.wide ? "wide" : "standard"]);
  const closed = useWorkspace((state) => state.closed);
  const datasetId = useWorkspace((state) => state.datasetId);
  const reportId = useWorkspace((state) => state.reportId);
  const path = useRouterState({ select: (state) => state.location.pathname });
  const [sidebarOpen, setSidebarOpen] = useState(readSidebarOpen);
  if (expired)
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <Empty>
          <EmptyHeader>
            <EmptyTitle>会话已失效，请重新运行 gleanery 打开应用</EmptyTitle>
          </EmptyHeader>
        </Empty>
      </main>
    );
  // 列表页没打开内容时工作区是空的，把宽度还给列表。保持挂载，定位请求才不会中断。
  const listEmpty = (path === "/datasets" || path === "/reports") && !datasetId && !reportId;
  const workspaceHidden = listEmpty || closed;
  const workspaceWidth = width ? `${width}px` : wide ? "max(50%,560px)" : "clamp(400px,33vw,470px)";
  return (
    <SidebarProvider
      open={sidebarOpen}
      onOpenChange={(open) => {
        setSidebarOpen(open);
        saveSidebarOpen(open);
      }}
      // 收起时面板内宽要正好是 32px 图标按钮加两侧 12px，默认的 3rem 少 2px，按钮会偏右。
      style={{ "--sidebar-width": "244px", "--sidebar-width-icon": "50px" } as React.CSSProperties}
      className="md:h-screen"
    >
      <SettingsDialog />
      <DisclaimerDialog />
      <ChatgptNoticeDialog />
      <ConfirmHost />
      <Toaster />
      <AppSidebar />
      <div
        style={{ "--workspace-width": workspaceWidth } as React.CSSProperties}
        className={`grid min-w-0 flex-1 grid-cols-1 gap-3 p-3 md:min-h-0 ${
          workspaceHidden
            ? ""
            : "md:grid-cols-[minmax(340px,1fr)_minmax(0,min(var(--workspace-width),calc(100%-352px)))]"
        }`}
      >
        <div className="relative flex min-h-0 min-w-0 flex-col">
          {closed && !listEmpty && (
            <Button
              autoFocus
              variant="ghost"
              size="icon-sm"
              aria-label="打开工作区"
              className="absolute top-1.5 right-2 z-10 md:top-3"
              onClick={() => useWorkspace.getState().setClosed(false)}
            >
              <PanelRightOpen />
            </Button>
          )}
          <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3 md:hidden">
            <SidebarTrigger aria-label="切换左栏" />
            <Link to="/" className="font-semibold">
              Gleanery
            </Link>
          </div>
          <ConversationHeader />
          <main className="min-h-[400px] min-w-0 flex-1 overflow-hidden">
            <Outlet />
          </main>
        </div>
        {/* 隐藏时保持挂载：未保存的编辑和进行中的定位请求都不能丢。 */}
        <div className={`relative flex min-h-0 min-w-0 ${workspaceHidden ? "hidden" : ""}`}>
          <WorkspaceResizer />
          <Workspace className="flex-1" />
        </div>
      </div>
    </SidebarProvider>
  );
}
