import { create } from "zustand";
type Tab = "plan" | "collect" | "dataset" | "report";
type Approval = (approved: boolean, reason?: string) => Promise<void>;
/** 按 ID 定位。不给数据集时由 `/api/locate` 找。 */
export type FocusTarget = { datasetId?: number; contentId: number; commentId?: number };
// 表格和报告正文在标准宽度里挤不下，切到这两个标签时用宽档，切走时收回。
const needsWide = (tab: Tab) => tab === "dataset" || tab === "report";
/** 用户拖出来的宽度，宽窄两档各记各的。null 表示用默认宽度。 */
type Widths = { standard: number | null; wide: number | null };
const widthsKey = "gleanery.workspaceWidths";

function readWidths(): Widths {
  try {
    const saved = JSON.parse(localStorage.getItem(widthsKey) ?? "null");
    return {
      standard: typeof saved?.standard === "number" ? saved.standard : null,
      wide: typeof saved?.wide === "number" ? saved.wide : null,
    };
  } catch {
    return { standard: null, wide: null };
  }
}

function saveWidths(widths: Widths) {
  try {
    localStorage.setItem(widthsKey, JSON.stringify(widths));
  } catch {
    // 存不下只影响下次启动时的宽度
  }
}

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
  widths: Widths;
  /** 用户关掉了工作区。Agent 推进阶段不会重新打开，用户点进工作区才打开。 */
  closed: boolean;
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
  /** 设置当前档位的宽度，传 null 恢复默认。 */
  setWidth: (width: number | null) => void;
  setClosed: (v: boolean) => void;
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
  widths: readWidths(),
  closed: false,
  reportId: null,
  writing: false,
  select: (tab) =>
    set((s) => ({
      tab,
      wide: needsWide(tab),
      closed: false,
      notices: s.notices.filter((n) => n !== tab),
    })),
  auto: (tab) =>
    set((s) =>
      s.editing || s.dirty
        ? { notices: [...new Set([...s.notices, tab])] }
        : { tab, wide: needsWide(tab), notices: s.notices.filter((n) => n !== tab) },
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
            closed: false,
            notices: s.notices.filter((n) => n !== "dataset"),
          },
    ),
  focus: (target) =>
    set((s) => ({
      pendingFocus: target,
      datasetId: target.datasetId ?? s.datasetId,
      tab: "dataset",
      wide: true,
      closed: false,
      notices: s.notices.filter((n) => n !== "dataset"),
    })),
  clearFocus: () => set({ pendingFocus: null }),
  setWide: (wide) => set({ wide }),
  setWidth: (width) =>
    set((s) => {
      const widths = { ...s.widths, [s.wide ? "wide" : "standard"]: width };
      saveWidths(widths);
      return { widths };
    }),
  setClosed: (closed) => set({ closed }),
  openReport: (reportId) =>
    set((s) =>
      reportId === null
        ? { reportId }
        : {
            reportId,
            tab: "report",
            wide: true,
            closed: false,
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
            wide: true,
            notices: s.notices.filter((n) => n !== "report"),
          },
    ),
  setWriting: (writing) => set({ writing }),
}));
