export const riskNotificationKey = "gleanery.notify-risk";

export function notifyRisk(platform: "bili" | "xhs") {
  if (
    localStorage.getItem(riskNotificationKey) !== "true" ||
    !document.hidden ||
    !("Notification" in window) ||
    Notification.permission !== "granted"
  )
    return;
  const notification = new Notification(
    `${platform === "bili" ? "B 站" : "小红书"}触发风控，采集已暂停`,
  );
  notification.onclick = () => window.focus();
}
