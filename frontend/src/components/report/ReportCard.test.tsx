import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useWorkspace } from "@/stores/workspace";
import { ReportCard } from "./ReportCard";
import type { ComponentProps } from "react";

const state = vi.hoisted(() => ({ messages: [] as unknown[] }));
vi.mock("@assistant-ui/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@assistant-ui/react")>()),
  useAuiState: (selector: (s: unknown) => unknown) => selector({ thread: state }),
}));
type Props = ComponentProps<typeof ReportCard>;
const props = {
  type: "tool-call",
  toolName: "save_report",
  toolCallId: "one",
  args: {},
  argsText: "{}",
  status: { type: "complete" },
  result: {
    report_id: 1,
    title: "报告标题",
    version: 1,
    basis: { dataset_name: "数据集", contents: 3, comments: 5, recorded_at: 1 },
  },
} as Props;

test("只让同一报告最后一张卡片通知工作区，打开按钮可主动切换", async () => {
  state.messages = [
    {
      content: [
        { type: "tool-call", toolName: "save_report", toolCallId: "one", result: props.result },
        { type: "tool-call", toolName: "update_report", toolCallId: "two", result: props.result },
      ],
    },
  ];
  useWorkspace.setState({ reportId: null, tab: "plan" });
  const { rerender } = render(<ReportCard {...props} />);
  expect(useWorkspace.getState().reportId).toBeNull();
  rerender(<ReportCard {...props} toolName="update_report" toolCallId="two" />);
  expect(useWorkspace.getState().reportId).toBe(1);
  expect(screen.getByText("基于 3 条内容、5 条评论 · 数据集")).toBeInTheDocument();
  expect(screen.getByText("已更新为第 1 版")).toBeInTheDocument();
  useWorkspace.setState({ tab: "plan" });
  await userEvent.click(screen.getByRole("button", { name: "在工作区打开" }));
  expect(useWorkspace.getState().tab).toBe("report");
});

test("错误和读取工具显示一行说明", () => {
  state.messages = [];
  const { rerender } = render(
    <ReportCard {...props} result={{ error: { code: "VERSION_CONFLICT" } }} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("报告刚被修改过");
  rerender(<ReportCard {...props} toolName="list_reports" result={{}} />);
  expect(screen.getByText("已查看报告列表")).toBeInTheDocument();
});

test("撰写中置工作区标记，有结果后清掉", () => {
  state.messages = [];
  useWorkspace.setState({ writing: false });
  const { rerender } = render(
    <ReportCard {...props} status={{ type: "running" }} result={undefined} />,
  );
  expect(useWorkspace.getState().writing).toBe(true);
  rerender(<ReportCard {...props} />);
  expect(useWorkspace.getState().writing).toBe(false);
});
