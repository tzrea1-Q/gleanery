function pad(value: number) {
  return String(value).padStart(2, "0");
}

/** 毫秒时间戳转成本地时区的 `2024-11-12`。表格放不下时间时用，完整时间放进 `title`。 */
export function formatDate(ms: number) {
  return formatDateTime(ms).slice(0, 10);
}

/** 毫秒时间戳转成本地时区的 `2024-11-12 03:11`，不跟随浏览器语言。 */
export function formatDateTime(ms: number, options?: { seconds?: boolean }) {
  const d = new Date(ms);
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${date} ${time}${options?.seconds ? `:${pad(d.getSeconds())}` : ""}`;
}
