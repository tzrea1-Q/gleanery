import { useState } from "react";
import { api } from "@/api/client";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { useComposer } from "@/stores/composer";

export type EventData = {
  type: "collection_finished" | "collection_paused" | "follow_up_failed";
  plan_id: number;
  plan_title?: string;
  tasks?: { processed: number; planned: number }[];
  auto_run?: string;
  platform?: string;
  reason?: string;
  message?: string;
};

export function EventCard({
  event,
  conversationId,
  running,
  last,
}: {
  event: EventData;
  conversationId: number;
  running: boolean;
  last: boolean;
}) {
  const [error, setError] = useState("");
  const retry = async () => {
    const { response, error } = await api.POST("/api/conversations/{conversation_id}/follow-up", {
      params: { path: { conversation_id: conversationId } },
      body: { plan_id: event.plan_id },
    });
    setError(
      response.ok
        ? ""
        : ((error && "message" in error ? error.message : undefined) ?? "继续整理失败，请重试"),
    );
  };
  const retryable =
    event.type === "follow_up_failed" ||
    (event.type === "collection_finished" &&
      (["incomplete", "no_model", "approval_pending"].includes(event.auto_run ?? "") ||
        (event.auto_run === "started" && last && !running)));
  return (
    <section
      aria-label="采集事件"
      className="my-3 space-y-2 rounded-2xl bg-muted px-4 py-2.5 text-muted-foreground"
    >
      {event.type === "collection_finished" && (
        <p>
          采集结束：计划「{event.plan_title}」实得{" "}
          {event.tasks?.reduce((n, t) => n + t.processed, 0)} / 计划{" "}
          {event.tasks?.reduce((n, t) => n + t.planned, 0)}
        </p>
      )}
      {event.type === "collection_finished" && event.auto_run === "started" && running && (
        <p>Agent 正在按后续意图整理…</p>
      )}
      {event.type === "collection_paused" && (
        <p>
          {event.platform === "bili" ? "B 站" : "小红书"}任务
          {event.reason === "risk"
            ? "触发风控已暂停，到进度卡片里选择继续或停止"
            : "登录失效，到左栏扫码"}
        </p>
      )}
      {event.type === "follow_up_failed" && <p>{event.message}</p>}
      {retryable && (
        <Button size="sm" onClick={() => void retry()}>
          {event.auto_run === "incomplete" ? "用已有数据继续整理" : "继续整理"}
        </Button>
      )}
      {event.auto_run === "incomplete" && (
        <Button
          variant="outline"
          size="sm"
          className="ml-2"
          onClick={() => useComposer.getState().prefill("补采")}
        >
          补采
        </Button>
      )}
      {error && <Notice>{error}</Notice>}
    </section>
  );
}
