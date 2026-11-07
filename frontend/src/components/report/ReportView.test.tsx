import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { registerReportEvents } from "@/lib/events-report";
import { useComposer } from "@/stores/composer";
import { useWorkspace } from "@/stores/workspace";
import { server } from "@/test/server";
import { ReportView } from "./ReportView";

const original = {
  id: 1,
  title: "报告一",
  version: 1,
  markdown: "原文",
  dataset_id: 1,
  dataset_name: "数据集",
  created_in_conversation_id: 1,
  conversation_title: null,
  created_at: 1,
  updated_at: 1,
  updated_by: "agent",
  basis: { dataset_name: "数据集", contents: 3, comments: 4, recorded_at: 1 },
  new_since: 2,
  citations: [],
};
let current = { ...original };
let saves: { base_version: number; title: string; markdown: string }[] = [];
let header: string | null = null;
function setup() {
  current = { ...original };
  saves = [];
  header = null;
  server.use(
    http.get("*/api/reports", () =>
      HttpResponse.json({ items: [current, { ...original, id: 2, title: "报告二" }], total: 2 }),
    ),
    http.get("*/api/reports/:id", ({ params }) =>
      HttpResponse.json(
        Number(params.id) === 1 ? current : { ...original, id: 2, title: "报告二" },
      ),
    ),
    http.get("*/api/reports/:id/revisions", () =>
      HttpResponse.json([
        { id: 5, version: 1, title: "历史", source: "agent", conversation_id: 1, created_at: 1 },
      ]),
    ),
    http.get("*/api/reports/:id/revisions/:revision", () =>
      HttpResponse.json({
        id: 5,
        version: 1,
        title: "历史",
        markdown: "历史正文",
        source: "agent",
        conversation_id: 1,
        created_at: 1,
      }),
    ),
    http.post("*/api/reports/:id/revisions/:revision/restore", () => {
      current = { ...current, version: current.version + 1, markdown: "历史正文" };
      return HttpResponse.json(current);
    }),
    http.put("*/api/conversations/:id/workspace", () => HttpResponse.json({ report_id: 1 })),
    http.put("*/api/reports/:id", async ({ request }) => {
      const body = (await request.json()) as (typeof saves)[number];
      saves.push(body);
      header = request.headers.get("X-Conversation-Id");
      if (body.base_version !== current.version)
        return HttpResponse.json(
          { code: "VERSION_CONFLICT", message: "冲突", hint: null },
          { status: 409 },
        );
      current = { ...current, ...body, version: current.version + 1, updated_by: "user" };
      return HttpResponse.json(current);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReportView conversationId={1} />
    </QueryClientProvider>,
  );
  return client;
}
afterEach(() => {
  useWorkspace.setState({ reportId: null, editing: false, dirty: false });
  useComposer.getState().register(null);
  vi.restoreAllMocks();
});
test("编辑、预览、保存并携带对话", async () => {
  setup();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "编辑" }));
  await user.clear(screen.getByLabelText("Markdown 源码"));
  await user.type(screen.getByLabelText("Markdown 源码"), "修改正文");
  expect(useWorkspace.getState().dirty).toBe(true);
  await user.click(screen.getByRole("button", { name: "预览" }));
  expect(screen.getByText("修改正文")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(header).toBe("1"));
  expect(saves[0].markdown).toBe("修改正文");
});
test.each(["用我的覆盖", "放弃我的修改"])("冲突时%s", async (choice) => {
  setup();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "编辑" }));
  await user.type(screen.getByLabelText("Markdown 源码"), "我的");
  current = { ...current, version: 2, markdown: "Agent 正文" };
  await user.click(screen.getByRole("button", { name: "保存" }));
  const dialog = await screen.findByRole("dialog", { name: "保存冲突" });
  expect(within(dialog).getByText(/Agent 正文/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: choice }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  if (choice === "用我的覆盖") expect(saves.at(-1)?.base_version).toBe(2);
  else expect(screen.getByText("Agent 正文")).toBeInTheDocument();
});
test("编辑时 Agent 更新只提醒，历史恢复、切换和预填", async () => {
  const client = setup();
  const prefill = vi.fn();
  useComposer.getState().register(prefill);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "让 Agent 更新" }));
  expect(prefill).toHaveBeenCalledWith("数据集有新内容，请更新报告「报告一」");
  await user.click(screen.getByRole("button", { name: "编辑" }));
  await user.type(screen.getByLabelText("Markdown 源码"), "我的");
  current = { ...current, version: 2, markdown: "新正文" };
  const events = new EventTarget();
  registerReportEvents(events as EventSource, client);
  events.dispatchEvent(
    new MessageEvent("report.updated", {
      data: JSON.stringify({ report_id: 1, version: 2, source: "agent" }),
    }),
  );
  expect(await screen.findByText("Agent 已更新此报告（第 2 版）")).toBeInTheDocument();
  expect(screen.getByLabelText("Markdown 源码")).toHaveValue("原文我的");
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "历史版本" }));
  await user.click(await screen.findByRole("button", { name: /第 1 版/ }));
  expect(await screen.findByText("历史正文")).toBeInTheDocument();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "恢复此版本" }));
  await waitFor(() => expect(current.version).toBe(3));
  await user.selectOptions(screen.getByLabelText("报告"), "2");
  expect(await screen.findByRole("heading", { name: "报告二" })).toBeInTheDocument();
});
