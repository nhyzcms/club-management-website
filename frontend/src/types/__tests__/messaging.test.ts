import { describe, expect, it } from "vitest";
import {
  hostQuery,
  NOTIFICATION_CATEGORY_LABELS,
  notificationHref,
  notificationTitle,
  withinRetractWindow,
} from "../messaging";

describe("withinRetractWindow", () => {
  it("3 分钟内可撤回，超时不可", () => {
    const now = Date.now();
    expect(withinRetractWindow(new Date(now - 60_000).toISOString(), now)).toBe(true);
    expect(withinRetractWindow(new Date(now - 4 * 60_000).toISOString(), now)).toBe(false);
  });

  it("非法时间 → false", () => {
    expect(withinRetractWindow("not-a-date")).toBe(false);
  });
});

describe("hostQuery", () => {
  it("按宿主类型产出查询参数", () => {
    expect(hostQuery({ news: 3 })).toEqual({ news: "3" });
    expect(hostQuery({ activity: 5 })).toEqual({ activity: "5" });
    expect(hostQuery({ task: 9 })).toEqual({ task: "9" });
  });
});

describe("notificationHref / notificationTitle", () => {
  it("href：url 优先（相对补 /），回退各实体 id，缺省 null", () => {
    expect(notificationHref({ payload: { url: "/news/1" } } as any)).toBe("/news/1");
    expect(notificationHref({ payload: { url: "news/1" } } as any)).toBe("/news/1");
    expect(notificationHref({ payload: { news_id: 2 } } as any)).toBe("/news/2");
    expect(notificationHref({ payload: { activity_id: 3 } } as any)).toBe("/activity/3");
    expect(notificationHref({ payload: {} } as any)).toBe(null);
  });

  it("title：事件文案 → 分类文案 → 兜底", () => {
    expect(notificationTitle({ event: "approved", category: "review" } as any)).toBe("内容已通过审核");
    expect(notificationTitle({ event: "unknown_x", category: "review" } as any)).toBe("审核");
    expect(notificationTitle({ event: "unknown_x", category: "weird" } as any)).toBe("通知");
  });

  it("title：聚合后的私信通知报累计条数", () => {
    expect(
      notificationTitle({ event: "new_message", category: "dm", payload: { count: 3 } } as any),
    ).toBe("你收到 3 条新私信");
    expect(
      notificationTitle({ event: "new_message", category: "dm", payload: {} } as any),
    ).toBe("你收到一条新私信");
  });

  it("分类文案：私信有徽标文案", () => {
    expect(NOTIFICATION_CATEGORY_LABELS.dm).toBe("私信");
  });
});
