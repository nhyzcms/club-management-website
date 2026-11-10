import { beforeEach, describe, expect, it } from "vitest";
import {
  ANNOUNCEMENT_SEEN_KEY,
  filterUnseenAnnouncements,
  isAnnouncementSeen,
  rememberAnnouncementSeen,
  seenAnnouncementIds,
} from "../announcementSeen";

describe("announcementSeen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("记住后不再出现在未看列表里，且重复记住不产生重复项", () => {
    rememberAnnouncementSeen(3);
    rememberAnnouncementSeen(3);
    expect(seenAnnouncementIds()).toEqual([3]);
    expect(isAnnouncementSeen(3)).toBe(true);
    expect(filterUnseenAnnouncements([{ id: 3 }, { id: 4 }])).toEqual([{ id: 4 }]);
  });

  it("只保留最近 100 条（防止 localStorage 无限增长）", () => {
    for (let i = 1; i <= 105; i += 1) rememberAnnouncementSeen(i);
    const ids = seenAnnouncementIds();
    expect(ids).toHaveLength(100);
    expect(ids[0]).toBe(6);
    expect(ids[ids.length - 1]).toBe(105);
  });

  it("存了脏数据时按「没看过」处理，不抛异常", () => {
    window.localStorage.setItem(ANNOUNCEMENT_SEEN_KEY, "{not json");
    expect(seenAnnouncementIds()).toEqual([]);
    window.localStorage.setItem(ANNOUNCEMENT_SEEN_KEY, JSON.stringify(["x", 2, null]));
    expect(seenAnnouncementIds()).toEqual([2]);
  });
});
