import createClient from "openapi-fetch";
import type { paths } from "./schema";

// 前端只用相对 URL。启动令牌 Cookie 由浏览器自动带上。
export const api = createClient<paths>({ baseUrl: "" });
