import { createContext } from "react";

/**
 * 这一轮在别处发起（切走后切回、另一个标签页），本页没有它的流。
 * 期间页面上的待审批卡片多半已经批过，不再给按钮，跑完后整轮一起显示。
 */
export const ReplyingContext = createContext(false);
