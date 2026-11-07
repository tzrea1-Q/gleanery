import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

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
      <h2 className="font-semibold">数据</h2>
      {settings.isPending && <p>正在加载数据设置…</p>}
      {settings.isError && <p role="alert">无法加载数据设置</p>}
      {settings.data && (
        <>
          <label>
            原始响应留存
            <select
              className="ml-2 rounded border p-2"
              value={settings.data.raw_retention_days ?? "forever"}
              disabled={update.isPending}
              onChange={(e) =>
                update.mutate(
                  e.target.value === "forever" ? null : (Number(e.target.value) as Retention),
                )
              }
            >
              <option value="7">7 天</option>
              <option value="30">30 天</option>
              <option value="90">90 天</option>
              <option value="forever">永久</option>
            </select>
          </label>
          <p>改动后立即按新天数清理</p>
          <p>
            原始响应 {settings.data.raw_count} 条，{size(settings.data.raw_bytes)}
          </p>
          <p>数据库总大小 {size(settings.data.db_bytes)}</p>
        </>
      )}
      <button
        className="rounded border p-2"
        onClick={() => {
          setMessage("");
          setConfirmRaw(true);
        }}
      >
        清空全部原始响应
      </button>
      {confirmRaw && (
        <div role="alertdialog" aria-label="确认清空原始响应">
          <p>确定清空全部原始响应？删除后无法恢复。</p>
          <button
            className="rounded border p-2"
            disabled={purge.isPending}
            onClick={() => purge.mutate()}
          >
            确认清空
          </button>{" "}
          <button className="rounded border p-2" onClick={() => setConfirmRaw(false)}>
            取消
          </button>
        </div>
      )}
      <div>
        <button
          className="rounded border p-2"
          onClick={() => {
            setMessage("");
            setConfirmAll(true);
          }}
        >
          删除所有采集数据
        </button>
      </div>
      {confirmAll && (
        <div role="alertdialog" aria-label="确认删除所有采集数据">
          {impact.isFetching && <p>正在计算删除影响…</p>}
          {impact.isError && <p role="alert">无法加载删除影响，请关闭后重试</p>}
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
              <button
                className="rounded border p-2"
                disabled={clear.isPending}
                onClick={() => clear.mutate(impact.data.active_task_ids.length > 0)}
              >
                {impact.data.active_task_ids.length ? "停止这些任务并删除" : "确认删除"}
              </button>{" "}
            </>
          )}
          <button className="rounded border p-2" onClick={() => setConfirmAll(false)}>
            取消
          </button>
        </div>
      )}
      {(update.isError || purge.isError || clear.isError) && <p role="alert">操作失败，请重试</p>}
      {message && <p role="status">{message}</p>}
      <p>本地数据不额外加密，依靠系统磁盘加密（FileVault / BitLocker）。</p>
    </div>
  );
}
