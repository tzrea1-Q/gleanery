import { Notice } from "@/components/common/Notice";
import { createContext, useContext, useEffect, useState } from "react";
import { useComposer } from "@/stores/composer";
import { AssistantRuntimeProvider, useAui, useAuiState } from "@assistant-ui/react";
import { AssistantChatTransport, useChatRuntime } from "@assistant-ui/react-ai-sdk";
import { lastAssistantMessageIsCompleteWithApprovalResponses, type UIMessage } from "ai";
import {
  Thread,
  UserMessage as DefaultUserMessage,
} from "@/components/assistant-ui/elements/thread.aui";
import { EventCard, type EventData } from "./EventCard";
import { ChatAssistantMessage } from "./ChatAssistantMessage";
import { FirstRunCard } from "@/components/model/FirstRunCard";
import { ModelSelector } from "@/components/model/ModelSelector";
import { checkSession, useAppState, useConversation } from "@/api/queries";
import { ReplyingContext } from "@/lib/replying";

/** 后台事件或回复落库时 Chat 会重挂，切换对话也会卸载；输入框里没发出去的草稿按对话记下来，重挂后放回去。 */
const drafts = new Map<string, string>();

function ComposerBridge({ id }: { id: string }) {
  const aui = useAui();
  useEffect(() => {
    const composer = aui.thread.composer();
    const draft = drafts.get(id);
    if (draft) composer.setText(draft);
    useComposer.getState().register((text) => composer.setText(text));
    return () => {
      drafts.set(id, composer.getState().text);
      useComposer.getState().register(null);
    };
  }, [aui, id]);
  return null;
}

export function FirstRunSlot() {
  return <FirstRunCard />;
}

const EventContext = createContext<{ messages: UIMessage[]; id: string; running: boolean }>({
  messages: [],
  id: "",
  running: false,
});

function UserMessage() {
  const { messages, id, running } = useContext(EventContext);
  const messageId = useAuiState((s) => s.message.id);
  const index = useAuiState((s) => s.message.index);
  const event = (
    messages.find((message) => message.id === messageId)?.metadata as
      { gleanery_event?: EventData } | undefined
  )?.gleanery_event;
  if (event)
    return (
      <EventCard
        event={event}
        conversationId={Number(id)}
        running={running}
        last={index === messages.length - 1}
      />
    );
  return <DefaultUserMessage />;
}

function RunningBridge({
  onLocalRunning,
  onLocalFailed,
}: {
  onLocalRunning: (running: boolean) => void;
  onLocalFailed: (failed: boolean) => void;
}) {
  const localRunning = useAuiState((s) => s.thread.isRunning);
  const localFailed = useAuiState((s) => {
    const status = s.thread.messages.at(-1)?.status;
    return status?.type === "incomplete" && status.reason === "error";
  });
  useEffect(() => onLocalRunning(localRunning), [localRunning, onLocalRunning]);
  useEffect(() => onLocalFailed(localFailed), [localFailed, onLocalFailed]);
  return null;
}

function Chat({
  id,
  messages,
  disabled,
  running,
  replying,
  localFailed,
  onLocalRunning,
  onLocalFailed,
}: {
  id: string;
  messages: UIMessage[];
  disabled: boolean;
  running: boolean;
  replying: boolean;
  localFailed: boolean;
  onLocalRunning: (running: boolean) => void;
  onLocalFailed: (failed: boolean) => void;
}) {
  const runtime = useChatRuntime({
    id,
    messages,
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
    transport: new AssistantChatTransport({
      api: "/api/chat",
      fetch: async (input, init) => checkSession(await fetch(input, init)),
      // 历史由服务端保存，只发最后一条；trigger 是后端区分发送与重新生成的判别字段。
      prepareSendMessagesRequest: ({ messages, trigger, messageId }) => ({
        body: { id, trigger, messageId, messages: messages.slice(-1) },
      }),
    }),
  });
  return (
    <EventContext.Provider value={{ messages, id, running }}>
      <ReplyingContext.Provider value={replying}>
        <AssistantRuntimeProvider runtime={runtime}>
          <div className="flex h-full min-h-0 flex-col">
            <ComposerBridge id={id} />
            <RunningBridge onLocalRunning={onLocalRunning} onLocalFailed={onLocalFailed} />
            {running && <p role="status">Agent 正在整理采集结果…</p>}
            {replying && <p role="status">Agent 正在回复，完成后显示…</p>}
            <FirstRunSlot />
            {/* 错误卡片也在这个 fieldset 里，整个禁用的话它的按钮就点不了，所以出错时只挡输入框 */}
            <fieldset
              disabled={disabled && !localFailed}
              className={`min-h-0 min-w-0 w-full flex-1 border-0 p-0 ${
                disabled && localFailed
                  ? "[&_.aui-composer-root]:pointer-events-none [&_.aui-composer-root]:opacity-50"
                  : ""
              }`}
            >
              <Thread
                autoFocus={false}
                components={{
                  AssistantMessage: ChatAssistantMessage,
                  UserMessage,
                  ComposerExtra: ModelSelector,
                  Welcome: () => <p className="mb-6 text-2xl">开始一段新对话</p>,
                }}
              />
            </fieldset>
          </div>
        </AssistantRuntimeProvider>
      </ReplyingContext.Provider>
    </EventContext.Provider>
  );
}

export function ConversationThread({ id }: { id: string }) {
  const conversation = useConversation(Number(id));
  const appState = useAppState();
  const [localRunning, setLocalRunning] = useState(false);
  const [localFailed, setLocalFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const [seenMessages, setSeenMessages] = useState("");
  const messageKey = JSON.stringify(conversation.data?.messages ?? []);
  // 出错的一轮不落库，服务端停在这一轮的用户消息上。这时重挂会清掉错误卡片和已流出的内容；
  // 服务端有了新内容（比如来了事件）才重挂。不能比条数：本地会合并相邻的助手消息，两边对不上。
  const last = conversation.data?.messages.at(-1) as UIMessage | undefined;
  const behindLocal =
    localFailed &&
    last?.role === "user" &&
    !(last.metadata as { gleanery_event?: unknown } | undefined)?.gleanery_event;
  if (
    !localRunning &&
    conversation.data?.running !== "chat" &&
    seenMessages !== messageKey &&
    !behindLocal
  ) {
    setSeenMessages(messageKey);
    setRevision((value) => value + 1);
  }
  const replying = !localRunning && conversation.data?.running === "chat";
  if (conversation.isPending || appState.isPending) return <p className="p-6">正在加载对话…</p>;
  if (conversation.isError || appState.isError)
    return <Notice className="m-6 w-auto">无法加载对话，请重试</Notice>;
  return (
    <Chat
      key={`${id}-${revision}`}
      id={id}
      messages={conversation.data.messages as unknown as UIMessage[]}
      disabled={
        appState.data.current_model?.status !== "ok" ||
        conversation.data.running === "follow_up" ||
        replying
      }
      running={conversation.data.running === "follow_up"}
      replying={replying}
      localFailed={localFailed}
      onLocalRunning={setLocalRunning}
      onLocalFailed={setLocalFailed}
    />
  );
}
