import { useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import { useRouterState } from "@tanstack/react-router";
import { useReports } from "@/api/queries-report";
import { useDatasets, usePlans, useSavePlan, useTasks } from "@/api/queries-collect";
import type { components } from "@/api/schema";
import { Progress } from "@/components/collect/Progress";
import { DatasetTable } from "@/components/dataset/DatasetTable";
import { ReportView } from "@/components/report/ReportView";
import { useWorkspace } from "@/stores/workspace";

type Plan = components["schemas"]["PlanOut"];
type Body = components["schemas"]["PlanBody"];
const input = "block w-full rounded border bg-background p-1";
function PlanEditor({ plan }: { plan: Plan }) {
  const [body, setBody] = useState<Body>(plan.body);
  const [version, setVersion] = useState(plan.version);
  const [baseline, setBaseline] = useState(() => JSON.stringify(plan.body));
  const editing = useWorkspace((s) => s.editing);
  const [conflict, setConflict] = useState(false);
  const [reloadFailed, setReloadFailed] = useState(false);
  const datasets = useDatasets();
  const save = useSavePlan(plan.id);
  const setDirty = useWorkspace((s) => s.setDirty);
  const setEditing = useWorkspace((s) => s.setEditing);
  const approval = useWorkspace((s) => s.approvals[plan.id]);
  const dirty = JSON.stringify(body) !== baseline;
  if (plan.version > version && !dirty && !editing) {
    setBody(plan.body);
    setBaseline(JSON.stringify(plan.body));
    setVersion(plan.version);
  }
  useEffect(() => () => setEditing(false), [setEditing]);
  useEffect(() => {
    setDirty(dirty);
    return () => setDirty(false);
  }, [dirty, setDirty]);
  function section(index: number, patch: Partial<Body["sections"][number]>) {
    setBody((b) => ({
      ...b,
      sections: b.sections.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    }));
  }
  return (
    <form
      className="space-y-3"
      onFocus={() => setEditing(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setEditing(false);
      }}
      onSubmit={(e) => {
        e.preventDefault();
        setReloadFailed(false);
        save.mutate(
          { base_version: version, body },
          {
            onSuccess: (p) => {
              setBody(p.body);
              setBaseline(JSON.stringify(p.body));
              setVersion(p.version);
              setConflict(false);
            },
            onError: async (err) => {
              if (err.message === "VERSION_CONFLICT") {
                try {
                  const { data } = await api.GET("/api/plans/{plan_id}", {
                    params: { path: { plan_id: plan.id } },
                  });
                  if (!data) throw new Error("无法载入");
                  setBody(data.body);
                  setBaseline(JSON.stringify(data.body));
                  setVersion(data.version);
                  setConflict(true);
                } catch {
                  setReloadFailed(true);
                }
              }
            },
          },
        );
      }}
    >
      {conflict && <p role="alert">Agent 刚改过计划，已载入最新版本</p>}
      {reloadFailed && <p role="alert">无法载入最新计划，请重试保存</p>}
      {save.isError && save.error.message !== "VERSION_CONFLICT" && (
        <p role="alert">保存失败，请重试</p>
      )}
      <fieldset disabled={plan.status !== "draft"} className="space-y-3">
        <label>
          标题
          <input
            className={input}
            value={body.title}
            onChange={(e) => setBody({ ...body, title: e.target.value })}
          />
        </label>
        <label>
          目标数据集
          <select
            className={input}
            value={body.target_dataset_id ?? ""}
            onChange={(e) =>
              setBody({
                ...body,
                target_dataset_id: e.target.value ? Number(e.target.value) : null,
              })
            }
          >
            <option value="">新建数据集</option>
            {datasets.data?.map((d) => (
              <option value={d.id} key={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        {!body.target_dataset_id && (
          <>
            <label>
              数据集名称
              <input
                className={input}
                value={body.new_dataset_name ?? ""}
                onChange={(e) => setBody({ ...body, new_dataset_name: e.target.value })}
              />
            </label>
            <label>
              数据集说明
              <textarea
                className={input}
                value={body.new_dataset_description ?? ""}
                onChange={(e) => setBody({ ...body, new_dataset_description: e.target.value })}
              />
            </label>
          </>
        )}
        <label>
          后续意图
          <textarea
            className={input}
            value={body.follow_up ?? ""}
            onChange={(e) => setBody({ ...body, follow_up: e.target.value })}
          />
        </label>
        {body.sections.map((s, i) => (
          <fieldset key={i} className="space-y-2 rounded border p-2">
            <legend>{s.platform === "bili" ? "B 站" : "小红书"}</legend>
            <label>
              平台
              <select
                className={input}
                value={s.platform}
                onChange={(e) => section(i, { platform: e.target.value as typeof s.platform })}
              >
                <option value="bili">B 站</option>
                <option value="xhs">小红书</option>
              </select>
            </label>
            <button
              type="button"
              className="rounded border p-1"
              disabled={body.sections.length === 1}
              onClick={() =>
                setBody({ ...body, sections: body.sections.filter((_, index) => index !== i) })
              }
            >
              删除平台分段
            </button>
            <label>
              关键词（每行一个）
              <textarea
                className={input}
                value={(s.keywords ?? []).join("\n")}
                onChange={(e) => section(i, { keywords: e.target.value.split("\n") })}
              />
            </label>
            <label>
              指定内容（每行一个）
              <textarea
                className={input}
                value={(s.targets ?? []).join("\n")}
                onChange={(e) => section(i, { targets: e.target.value.split("\n") })}
              />
            </label>
            <label>
              数量
              <input
                className={input}
                type="number"
                min="0"
                value={s.quantity}
                onChange={(e) => section(i, { quantity: Number(e.target.value) })}
              />
            </label>
            <label>
              排序
              <select
                className={input}
                value={s.sort}
                onChange={(e) => section(i, { sort: e.target.value as typeof s.sort })}
              >
                <option value="default">默认</option>
                <option value="hot">热度</option>
                <option value="new">最新</option>
              </select>
            </label>
            <label>
              近几天
              <input
                className={input}
                type="number"
                min="1"
                value={s.time_range?.last_days ?? ""}
                onChange={(e) =>
                  section(i, {
                    time_range: {
                      ...s.time_range,
                      last_days: e.target.value ? Number(e.target.value) : null,
                    },
                  })
                }
              />
            </label>
            {(["start", "end"] as const).map((k) => (
              <label key={k}>
                {k === "start" ? "开始日期" : "结束日期"}
                <input
                  className={input}
                  type="date"
                  value={s.time_range?.[k] ?? ""}
                  onChange={(e) =>
                    section(i, { time_range: { ...s.time_range, [k]: e.target.value || null } })
                  }
                />
              </label>
            ))}
            <label>
              <input
                type="checkbox"
                checked={s.depth.detail}
                onChange={(e) => section(i, { depth: { ...s.depth, detail: e.target.checked } })}
              />{" "}
              详情
            </label>
            <label>
              评论数
              <input
                className={input}
                type="number"
                min="0"
                value={s.depth.comments}
                onChange={(e) =>
                  section(i, { depth: { ...s.depth, comments: Number(e.target.value) } })
                }
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={s.depth.sub_comments}
                onChange={(e) =>
                  section(i, { depth: { ...s.depth, sub_comments: e.target.checked } })
                }
              />{" "}
              二级评论
            </label>
            <label>
              每条二级评论数
              <input
                className={input}
                type="number"
                min="0"
                value={s.depth.sub_comments_per_root}
                onChange={(e) =>
                  section(i, {
                    depth: { ...s.depth, sub_comments_per_root: Number(e.target.value) },
                  })
                }
              />
            </label>
            {s.platform === "bili" && (
              <label>
                <input
                  type="checkbox"
                  checked={s.depth.subtitles}
                  onChange={(e) =>
                    section(i, { depth: { ...s.depth, subtitles: e.target.checked } })
                  }
                />{" "}
                字幕
              </label>
            )}
          </fieldset>
        ))}
        <button
          type="button"
          className="rounded border p-2"
          onClick={() =>
            setBody({
              ...body,
              sections: [
                ...body.sections,
                {
                  platform: "bili",
                  keywords: [],
                  targets: [],
                  quantity: 0,
                  sort: "default",
                  time_range: null,
                  depth: {
                    detail: true,
                    comments: 0,
                    sub_comments: false,
                    sub_comments_per_root: 0,
                    subtitles: false,
                  },
                },
              ],
            })
          }
        >
          添加平台分段
        </button>
        <button className="rounded border p-2" disabled={save.isPending || !dirty}>
          保存
        </button>
      </fieldset>
      {plan.status === "draft" && (
        <>
          <button
            type="button"
            className="rounded border p-2 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!approval || dirty}
            onClick={() => void approval?.(true)}
          >
            确认开始
          </button>
          {!approval && (
            <p className="text-sm text-muted-foreground">
              先在对话里说"开始"，Agent 发起审批后才能在这里确认
            </p>
          )}
          {dirty && approval && <p>请先保存计划</p>}
        </>
      )}
    </form>
  );
}
function WorkspaceContent({ id }: { id: number }) {
  const plans = usePlans(id);
  const reports = useReports({ conversation_id: id, limit: 1 });
  const tasks = useTasks({ conversation_id: id });
  const plan = plans.data?.at(-1);
  const tab = useWorkspace((s) => s.tab);
  const notices = useWorkspace((s) => s.notices);
  const selectedDatasetId = useWorkspace((s) => s.datasetId);
  const selectedReportId = useWorkspace((s) => s.reportId);
  const wide = useWorkspace((s) => s.wide);
  const setWide = useWorkspace((s) => s.setWide);
  const select = useWorkspace((s) => s.select);
  const auto = useWorkspace((s) => s.auto);
  const previous = useRef({ plan: 0, confirmed: false, complete: false });
  const currentTasks = tasks.data?.filter((t) => t.plan_id === plan?.id) ?? [];
  const complete = currentTasks.length > 0 && currentTasks.every((t) => t.status === "completed");
  useEffect(() => {
    if (!plan || useWorkspace.getState().pendingFocus) return;
    const prev = previous.current;
    if (prev.plan !== plan.id) {
      auto("plan");
      previous.current = { plan: plan.id, confirmed: false, complete: false };
    } else if (plan.status === "confirmed" && !prev.confirmed) auto("collect");
    if (complete && !prev.complete) auto("dataset");
    previous.current = { plan: plan.id, confirmed: plan.status === "confirmed", complete };
  }, [plan, complete, auto]);
  if (id && plans.isPending && !selectedDatasetId && !selectedReportId)
    return <p>正在加载工作区…</p>;
  if ((plans.isError || tasks.isError) && !selectedDatasetId && !selectedReportId)
    return <p role="alert">无法加载工作区</p>;
  if (
    !plan &&
    !selectedDatasetId &&
    !selectedReportId &&
    !reports.data?.items.length &&
    tab !== "report"
  )
    return (
      <p className="mt-5 text-sm text-muted-foreground">
        Agent 产出的计划、进度、数据集和报告会出现在这里
      </p>
    );
  const datasetId =
    selectedDatasetId ?? currentTasks[0]?.dataset_id ?? plan?.body.target_dataset_id;
  return (
    <>
      <nav aria-label="工作区阶段" className="my-4 flex flex-wrap gap-2 text-sm">
        <span>需求 ›</span>
        {(
          [
            ["plan", "计划"],
            ["collect", "采集"],
            ["dataset", "数据集"],
            ["report", "报告"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            aria-current={tab === key ? "page" : undefined}
            className="aria-[current=page]:font-bold"
            onClick={() => select(key)}
          >
            {label}
            {notices.includes(key) && " •"} ›
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "plan" && plan && <PlanEditor key={plan.id} plan={plan} />}{" "}
        {tab === "collect" &&
          (tasks.data?.length ? <Progress tasks={tasks.data} /> : <p>暂无采集任务</p>)}{" "}
        {tab === "dataset" && (
          <>
            <button onClick={() => setWide(!wide)}>{wide ? "收窄" : "加宽"}</button>
            {datasetId ? <DatasetTable key={datasetId} id={datasetId} /> : <p>暂无数据集</p>}
          </>
        )}{" "}
        {tab === "report" && <ReportView conversationId={id} />}
      </div>
    </>
  );
}
export function Workspace() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const id = Number(/^\/c\/(\d+)$/.exec(path)?.[1]);
  const previousConversation = useRef(id);
  const selected = useWorkspace((s) => s.datasetId);
  const selectedReport = useWorkspace((s) => s.reportId);
  const pending = useWorkspace((s) => s.pendingFocus);
  const [focusError, setFocusError] = useState("");
  useEffect(() => {
    if (previousConversation.current && previousConversation.current !== id && id) {
      useWorkspace.getState().openDataset(null);
      useWorkspace.getState().openReport(null);
    }
    if (id) previousConversation.current = id;
  }, [id]);
  useEffect(() => {
    if (!pending || selected) return;
    void api
      .GET("/api/locate", {
        params: {
          query: pending.commentId
            ? { comment_id: pending.commentId }
            : { content_id: pending.contentId },
        },
      })
      .then(({ data }) => {
        if (useWorkspace.getState().pendingFocus !== pending) return;
        if (data?.dataset_id) {
          setFocusError("");
          useWorkspace.getState().openDataset(data.dataset_id);
        } else {
          setFocusError(data ? "这条内容已不在任何数据集里" : "无法定位，请检查 ID 后重试");
          useWorkspace.getState().clearFocus();
        }
      })
      .catch(() => {
        if (useWorkspace.getState().pendingFocus === pending) {
          setFocusError("无法定位，请检查 ID 后重试");
          useWorkspace.getState().clearFocus();
        }
      });
  }, [pending, selected]);
  return (
    <aside aria-label="工作区" className="flex min-h-0 min-w-0 flex-col border-l bg-muted/20 p-5">
      <h2 className="font-semibold">工作区</h2>
      {focusError && <p role="alert">{focusError}</p>}
      {!id && !selected && !selectedReport && (
        <p className="mt-4 text-sm">需求 › 计划 › 采集 › 数据集 › 报告</p>
      )}
      {id || selected || selectedReport ? (
        <WorkspaceContent key={id || "datasets"} id={id || 0} />
      ) : (
        <p className="mt-5 text-sm text-muted-foreground">
          Agent 产出的计划、进度、数据集和报告会出现在这里
        </p>
      )}
    </aside>
  );
}
