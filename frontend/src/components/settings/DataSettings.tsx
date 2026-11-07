import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormRow } from "@/components/common/FormRow";
import { FormSelect } from "@/components/common/FormSelect";
import { Notice } from "@/components/common/Notice";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from "@/components/ui/item";

type Retention = components["schemas"]["DataSettingsUpdate"]["raw_retention_days"];

function size(bytes: number) {
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(2)} ${units[unit]}`;
}

export function DataSettings() {
  const client = useQueryClient();
  const [confirmRaw, setConfirmRaw] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [message, setMessage] = useState("");
  const settings = useQuery({
    queryKey: ["data-settings"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/data-settings");
      if (!response.ok || !data) throw new Error("无法加载数据设置");
      return data;
    },
  });
  const impact = useQuery({
    queryKey: ["data-impact"],
    enabled: confirmAll,
    staleTime: 0,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/data/impact");
      if (!response.ok || !data) throw new Error("无法加载删除影响");
      return data;
    },
  });
  const update = useMutation({
    mutationFn: async (raw_retention_days: Retention) => {
      const { response } = await api.PATCH("/api/data-settings", { body: { raw_retention_days } });
      if (!response.ok) throw new Error("保存失败");
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["data-settings"] }),
  });
  const purge = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST("/api/data-settings/purge-raw");
      if (!response.ok) throw new Error("清空失败");
    },
    onSuccess: async () => {
      setConfirmRaw(false);
      setMessage("原始响应已清空");
      await client.invalidateQueries({ queryKey: ["data-settings"] });
    },
  });
  const clear = useMutation({
    mutationFn: async (stop_active: boolean) => {
      const { response } = await api.POST("/api/data/clear", { body: { stop_active } });
      if (!response.ok) throw new Error("删除失败");
    },
    onSuccess: async () => {
      setConfirmAll(false);
      setMessage("采集数据已删除");
      await client.invalidateQueries();
    },
  });
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight">数据</h2>
      {settings.isPending && <p className="text-muted-foreground">正在加载数据设置…</p>}
      {settings.isError && <Notice>无法加载数据设置</Notice>}
      {settings.data && (
        <>
          <FormRow
            label="原始响应留存"
            description="改动后立即按新天数清理"
            className="grid-cols-[7rem_minmax(0,16rem)]"
          >
            <FormSelect
              value={String(settings.data.raw_retention_days ?? "forever")}
              disabled={update.isPending}
              onValueChange={(value) =>
                update.mutate(value === "forever" ? null : (Number(value) as Retention))
              }
              options={[
                { value: "7", label: "7 天" },
                { value: "30", label: "30 天" },
                { value: "90", label: "90 天" },
                { value: "forever", label: "永久" },
              ]}
            />
          </FormRow>
          <div className="grid gap-2 sm:grid-cols-2">
            <p className="rounded-2xl bg-muted/60 px-4 py-3 dark:bg-muted/40">
              原始响应 {settings.data.raw_count} 条，{size(settings.data.raw_bytes)}
            </p>
            <p className="rounded-2xl bg-muted/60 px-4 py-3 dark:bg-muted/40">
              数据库总大小 {size(settings.data.db_bytes)}
            </p>
          </div>
        </>
      )}
      <div className="space-y-2">
        <Item className="rounded-2xl border-0 bg-muted/60 dark:bg-muted/40">
          <ItemContent>
            <ItemTitle>原始响应</ItemTitle>
            <ItemDescription>只删采集时留存的接口响应，已采的内容不受影响</ItemDescription>
          </ItemContent>
          <ItemActions>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                setMessage("");
                setConfirmRaw(true);
              }}
            >
              清空全部原始响应
            </Button>
          </ItemActions>
        </Item>
        {confirmRaw && (
          <div
            role="alertdialog"
            aria-label="确认清空原始响应"
            className="space-y-2 rounded-2xl bg-attention-muted p-4 text-attention"
          >
            <p>确定清空全部原始响应？删除后无法恢复。</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setConfirmRaw(false)}>
                取消
              </Button>
              <Button
                variant="destructive"
                size="sm"
                disabled={purge.isPending}
                onClick={() => purge.mutate()}
              >
                确认清空
              </Button>
            </div>
          </div>
        )}
        <Item className="rounded-2xl border-0 bg-muted/60 dark:bg-muted/40">
          <ItemContent>
            <ItemTitle>采集数据</ItemTitle>
            <ItemDescription>数据集、内容、评论和采集任务</ItemDescription>
          </ItemContent>
          <ItemActions>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                setMessage("");
                setConfirmAll(true);
              }}
            >
              删除所有采集数据
            </Button>
          </ItemActions>
        </Item>
        {confirmAll && (
          <div
            role="alertdialog"
            aria-label="确认删除所有采集数据"
            className="space-y-2 rounded-2xl bg-attention-muted p-4 text-attention"
          >
            {impact.isFetching && <p>正在计算删除影响…</p>}
            {impact.isError && <p>无法加载删除影响，请关闭后重试</p>}
            {impact.data && !impact.isFetching && !impact.isError && (
              <>
                <p>
                  数据集 {impact.data.datasets} 条、内容 {impact.data.contents} 条、评论{" "}
                  {impact.data.comments} 条、采集任务 {impact.data.tasks} 条、原始响应{" "}
                  {impact.data.raw_captures} 条
                </p>
                <p>对话和报告保留；模型配置和登录态保留；删除后无法恢复。</p>
                {impact.data.active_task_ids.length > 0 && (
                  <p>有进行中的任务：{impact.data.active_task_ids.join("、")}</p>
                )}
              </>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setConfirmAll(false)}>
                取消
              </Button>
              {impact.data && !impact.isFetching && !impact.isError && (
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={clear.isPending}
                  onClick={() => clear.mutate(impact.data.active_task_ids.length > 0)}
                >
                  {impact.data.active_task_ids.length ? "停止这些任务并删除" : "确认删除"}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
      {(update.isError || purge.isError || clear.isError) && <Notice>操作失败，请重试</Notice>}
      {message && (
        <p role="status" className="text-muted-foreground">
          {message}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        本地数据不额外加密，依靠系统磁盘加密（FileVault / BitLocker）。
      </p>
    </div>
  );
}
