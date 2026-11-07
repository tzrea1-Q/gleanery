import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useComposer } from "@/stores/composer";
import { EventCard, type EventData } from "./EventCard";

const event: EventData = {
  type: "collection_finished",
  plan_id: 3,
  plan_title: "咖啡",
  tasks: [{ processed: 2, planned: 3 }],
  auto_run: "incomplete",
};

test("显示采集数量，补采只预填，继续整理提交计划", async () => {
  const prefill = vi.fn();
  const request = vi.fn();
  useComposer.getState().register(prefill);
  server.use(
    http.post("*/api/conversations/:id/follow-up", async ({ request: req }) => {
      request(await req.json());
      return new HttpResponse(null, { status: 202 });
    }),
  );
  render(<EventCard event={event} conversationId={1} running={false} last />);
  expect(screen.getByText(/实得 2 \/ 计划 3/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "补采" }));
  expect(prefill).toHaveBeenCalledWith("补采");
  await userEvent.click(screen.getByRole("button", { name: "用已有数据继续整理" }));
  expect(request).toHaveBeenCalledWith({ plan_id: 3 });
  useComposer.getState().register(null);
});
