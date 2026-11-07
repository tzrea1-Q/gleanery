import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useWorkspace } from "@/stores/workspace";
import { ReportList } from "./ReportList";

test("搜索、打开和确认删除报告", async () => {
  let deleted = false;
  server.use(
    http.get("*/api/reports", ({ request }) =>
      HttpResponse.json({
        items:
          deleted || new URL(request.url).searchParams.get("keyword") === "茶"
            ? []
            : [
                {
                  id: 7,
                  title: "咖啡报告",
                  version: 2,
                  dataset_id: 1,
                  dataset_name: "咖啡",
                  created_in_conversation_id: 9,
                  conversation_title: "来源",
                  created_at: 1,
                  updated_at: 1,
                  updated_by: "agent",
                },
              ],
        total: deleted || new URL(request.url).searchParams.get("keyword") === "茶" ? 0 : 1,
      }),
    ),
    http.delete("*/api/reports/7", () => {
      deleted = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const router = createRouter({
    routeTree: createRootRoute({ component: ReportList }),
    history: createMemoryHistory({ initialEntries: ["/reports"] }),
  });
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  expect(await screen.findByText("咖啡报告")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "来源" })).toHaveAttribute("href", "/c/9");
  await user.click(screen.getByRole("button", { name: "打开" }));
  expect(useWorkspace.getState().reportId).toBe(7);
  await user.type(screen.getByLabelText("搜索报告"), "茶");
  expect(await screen.findByText("没有找到报告")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("搜索报告"));
  await screen.findByText("咖啡报告");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "删除" }));
  await waitFor(() => expect(screen.queryByText("咖啡报告")).not.toBeInTheDocument());
});
