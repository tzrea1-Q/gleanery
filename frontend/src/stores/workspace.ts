import { create } from "zustand";
type Tab = "plan" | "collect" | "dataset" | "report";
type Approval = (approved: boolean, reason?: string) => Promise<void>;
/** 按 ID 定位。不给数据集时由 `/api/locate` 找。 */
export type FocusTarget = { datasetId?: number; contentId: number; commentId?: number };
export const useWorkspace = create<{
  tab: Tab;
  editing: boolean;
  dirty: boolean;
  notices: Tab[];
  approvals: Partial<Record<number, Approval>>;
  /** "数据集"标签显示的数据集；为 null 时用当前计划的目标数据集。 */
  datasetId: number | null;
  pendingFocus: FocusTarget | null;
  wide: boolean;
  /** "报告"标签显示的报告；为 null 时显示本对话最近更新的一份。 */
  reportId: number | null;
  /** Agent 正在调用 save_report / update_report，报告标签显示"正在撰写…"。 */
  writing: boolean;
  select: (tab: Tab) => void;
  auto: (tab: Tab) => void;
  setEditing: (v: boolean) => void;
  setDirty: (v: boolean) => void;
  register: (id: number, fn: Approval | undefined) => void;
  /** 用户主动打开某个数据集：切到"数据集"标签并加宽，不受"正在编辑不抢标签"的限制。 */
  openDataset: (id: number | null) => void;
  focus: (target: FocusTarget) => void;
  clearFocus: () => void;
  setWide: (v: boolean) => void;
  /** 用户主动打开某份报告：切到"报告"标签，不受"正在编辑不抢标签"的限制。传 null 只清空。 */
  openReport: (id: number | null) => void;
  /** Agent 新建或更新了报告：设为当前报告，用户正在编辑时只亮提醒。 */
  reportArrived: (id: number) => void;
  setWriting: (v: boolean) => void;
}>((set) => ({
  tab: "plan",
  editing: false,
  dirty: false,
  notices: [],
  approvals: {},
  datasetId: null,
  pendingFocus: null,
  wide: false,
  reportId: null,
  writing: false,
  // 数据集表格在 280px 宽的工作区里挤不下，切到"数据集"时加宽，切走时收回；用户仍可手动切换。
  select: (tab) =>
    set((s) => ({ tab, wide: tab === "dataset", notices: s.notices.filter((n) => n !== tab) })),
  auto: (tab) =>
    set((s) =>
      s.editing || s.dirty
        ? { notices: [...new Set([...s.notices, tab])] }
        : { tab, wide: tab === "dataset", notices: s.notices.filter((n) => n !== tab) },
    ),
  setEditing: (editing) => set({ editing }),
  setDirty: (dirty) => set({ dirty }),
  register: (id, fn) =>
    set((s) => {
      const approvals = { ...s.approvals };
      if (fn) approvals[id] = fn;
      else delete approvals[id];
      return { approvals };
    }),
  openDataset: (datasetId) =>
    set((s) =>
      datasetId === null
        ? { datasetId }
        : {
            datasetId,
            tab: "dataset",
            wide: true,
            notices: s.notices.filter((n) => n !== "dataset"),
          },
    ),
  focus: (target) =>
    set((s) => ({
      pendingFocus: target,
      datasetId: target.datasetId ?? s.datasetId,
      tab: "dataset",
      wide: true,
      notices: s.notices.filter((n) => n !== "dataset"),
    })),
  clearFocus: () => set({ pendingFocus: null }),
  setWide: (wide) => set({ wide }),
  openReport: (reportId) =>
    set((s) =>
      reportId === null
        ? { reportId }
        : {
            reportId,
            tab: "report",
            wide: false,
            notices: s.notices.filter((n) => n !== "report"),
          },
    ),
  reportArrived: (reportId) =>
    set((s) =>
      // 正在编辑时连当前报告也不换，免得编辑器被换成另一份。
      s.editing || s.dirty
        ? { notices: [...new Set([...s.notices, "report" as Tab])] }
        : {
            reportId,
            tab: "report",
            wide: false,
            notices: s.notices.filter((n) => n !== "report"),
          },
    ),
  setWriting: (writing) => set({ writing }),
}));
