import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useDatasets, useSavePlan } from "@/api/queries-collect";
import type { components } from "@/api/schema";
import { CheckRow } from "@/components/common/CheckRow";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { PlatformTag } from "@/components/common/PlatformTag";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspace } from "@/stores/workspace";

type Plan = components["schemas"]["PlanOut"];
type Body = components["schemas"]["PlanBody"];

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      {children}
    </div>
  );
}

export function PlanEditor({ plan }: { plan: Plan }) {
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
  const readOnly = plan.status !== "draft";
  return (
    <form
      className="flex flex-1 flex-col gap-4"
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
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xl font-semibold tracking-tight">采集计划</h3>
        <StatusBadge tone={readOnly ? "success" : "info"}>
          {readOnly ? "已确认" : "草稿"}
        </StatusBadge>
      </div>
      {conflict && <Notice tone="warning">Agent 刚改过计划，已载入最新版本</Notice>}
      {reloadFailed && <Notice>无法载入最新计划，请重试保存</Notice>}
      {save.isError && save.error.message !== "VERSION_CONFLICT" && (
        <Notice>保存失败，请重试</Notice>
      )}
      <fieldset disabled={readOnly} className="min-w-0 flex-1 space-y-4 border-0 p-0">
        <div className="space-y-2">
          <FormRow label="标题">
            <Input
              value={body.title}
              onChange={(e) => setBody({ ...body, title: e.target.value })}
            />
          </FormRow>
          <FormRow label="目标数据集">
            <FormSelect
              disabled={readOnly}
              value={body.target_dataset_id ? String(body.target_dataset_id) : ""}
              onValueChange={(value) =>
                setBody({ ...body, target_dataset_id: value ? Number(value) : null })
              }
              options={[
                { value: "", label: "新建数据集" },
                ...(datasets.data?.map((d) => ({ value: String(d.id), label: d.name })) ?? []),
              ]}
            />
          </FormRow>
          {!body.target_dataset_id && (
            <>
              <FormRow label="数据集名称">
                <Input
                  value={body.new_dataset_name ?? ""}
                  onChange={(e) => setBody({ ...body, new_dataset_name: e.target.value })}
                />
              </FormRow>
              <FormRow label="数据集说明">
                <Textarea
                  value={body.new_dataset_description ?? ""}
                  onChange={(e) => setBody({ ...body, new_dataset_description: e.target.value })}
                />
              </FormRow>
            </>
          )}
          <FormRow label="后续意图" description="采集结束后 Agent 接着做什么">
            <Textarea
              value={body.follow_up ?? ""}
              onChange={(e) => setBody({ ...body, follow_up: e.target.value })}
            />
          </FormRow>
        </div>
        {body.sections.map((s, i) => (
          <Collapsible key={i} defaultOpen className="rounded-2xl bg-muted/60 p-3 dark:bg-muted/40">
            <div className="flex items-center gap-2">
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="group/section -ml-2 min-w-0 flex-1 justify-start"
                  aria-label={`${s.platform === "bili" ? "B 站" : "小红书"}分段`}
                >
                  <ChevronDown className="transition-transform group-data-[state=closed]/section:-rotate-90" />
                  <PlatformTag platform={s.platform} />
                  <span className="truncate font-normal text-muted-foreground">
                    {(s.keywords ?? []).filter(Boolean).join("、") || "未填关键词"}
                  </span>
                </Button>
              </CollapsibleTrigger>
              {!readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="删除平台分段"
                  disabled={body.sections.length === 1}
                  onClick={() =>
                    setBody({ ...body, sections: body.sections.filter((_, index) => index !== i) })
                  }
                >
                  <Trash2 />
                </Button>
              )}
            </div>
            <CollapsibleContent className="mt-2 space-y-4">
              <Group title="采集什么">
                <FormRow label="平台">
                  <FormSelect
                    disabled={readOnly}
                    value={s.platform}
                    onValueChange={(value) => section(i, { platform: value as typeof s.platform })}
                    options={[
                      { value: "bili", label: "B 站" },
                      { value: "xhs", label: "小红书" },
                    ]}
                  />
                </FormRow>
                <FormRow label="关键词" description="每行一个">
                  <Textarea
                    value={(s.keywords ?? []).join("\n")}
                    onChange={(e) => section(i, { keywords: e.target.value.split("\n") })}
                  />
                </FormRow>
                <FormRow label="指定内容" description="每行一个">
                  <Textarea
                    value={(s.targets ?? []).join("\n")}
                    onChange={(e) => section(i, { targets: e.target.value.split("\n") })}
                  />
                </FormRow>
              </Group>
              <Group title="范围">
                <FormRow label="数量">
                  <Input
                    type="number"
                    min="0"
                    value={s.quantity}
                    onChange={(e) => section(i, { quantity: Number(e.target.value) })}
                  />
                </FormRow>
                <FormRow label="排序">
                  <FormSelect
                    disabled={readOnly}
                    value={s.sort}
                    onValueChange={(value) => section(i, { sort: value as typeof s.sort })}
                    options={[
                      { value: "default", label: "默认" },
                      { value: "hot", label: "热度" },
                      { value: "new", label: "最新" },
                    ]}
                  />
                </FormRow>
                <FormRow label="近几天">
                  <Input
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
                </FormRow>
                {(["start", "end"] as const).map((k) => (
                  <FormRow key={k} label={k === "start" ? "开始日期" : "结束日期"}>
                    <Input
                      type="date"
                      value={s.time_range?.[k] ?? ""}
                      onChange={(e) =>
                        section(i, { time_range: { ...s.time_range, [k]: e.target.value || null } })
                      }
                    />
                  </FormRow>
                ))}
              </Group>
              <Group title="采集深度">
                <CheckRow
                  label="详情"
                  disabled={readOnly}
                  checked={s.depth.detail}
                  onCheckedChange={(detail) => section(i, { depth: { ...s.depth, detail } })}
                />
                <FormRow label="评论数">
                  <Input
                    type="number"
                    min="0"
                    value={s.depth.comments}
                    onChange={(e) =>
                      section(i, { depth: { ...s.depth, comments: Number(e.target.value) } })
                    }
                  />
                </FormRow>
                <CheckRow
                  label="二级评论"
                  disabled={readOnly}
                  checked={s.depth.sub_comments}
                  onCheckedChange={(sub_comments) =>
                    section(i, { depth: { ...s.depth, sub_comments } })
                  }
                />
                <FormRow label="每条二级评论数">
                  <Input
                    type="number"
                    min="0"
                    value={s.depth.sub_comments_per_root}
                    onChange={(e) =>
                      section(i, {
                        depth: { ...s.depth, sub_comments_per_root: Number(e.target.value) },
                      })
                    }
                  />
                </FormRow>
                {s.platform === "bili" && (
                  <CheckRow
                    label="字幕"
                    disabled={readOnly}
                    checked={s.depth.subtitles}
                    onCheckedChange={(subtitles) =>
                      section(i, { depth: { ...s.depth, subtitles } })
                    }
                  />
                )}
              </Group>
            </CollapsibleContent>
          </Collapsible>
        ))}
        {!readOnly && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full border-dashed"
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
            <Plus />
            添加平台分段
          </Button>
        )}
      </fieldset>
      {!readOnly && (
        <div className="sticky bottom-0 -mx-4 -mb-4 space-y-2 border-t bg-card px-4 py-3">
          {!approval && (
            <p className="text-xs text-muted-foreground">
              先在对话里说"开始"，Agent 发起审批后才能在这里确认
            </p>
          )}
          {dirty && approval && <p className="text-xs text-muted-foreground">请先保存计划</p>}
          <div className="flex justify-end gap-2">
            <Button type="submit" variant="outline" disabled={save.isPending || !dirty}>
              保存
            </Button>
            <Button
              type="button"
              disabled={!approval || dirty}
              onClick={() => void approval?.(true)}
            >
              确认开始
            </Button>
          </div>
        </div>
      )}
    </form>
  );
}
