import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const conversations = [
  { id: 1, title: "已有对话", created_at: 1, updated_at: 1 },
  { id: 2, title: "", created_at: 2, updated_at: 2 },
];
export const server = setupServer(
  http.get("*/api/conversations", () => HttpResponse.json(conversations)),
  http.post("*/api/conversations", () =>
    HttpResponse.json({ id: 3, title: "", created_at: 3, updated_at: 3 }, { status: 201 }),
  ),
  http.get("*/api/conversations/:id", ({ params }) =>
    HttpResponse.json({
      id: Number(params.id),
      title: "",
      created_at: 1,
      updated_at: 1,
      messages: [],
    }),
  ),
  http.get("*/api/app-state", () =>
    HttpResponse.json({
      current_model: { config_id: 1, config_name: "测试", model: "测试模型", status: "ok" },
      disclaimer_acknowledged: true,
      credential_backend: "memory",
    }),
  ),
);
