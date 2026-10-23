# 全站弹窗公告 · API

> 设计记录：[ADR-0042](../adr/0042-site-wide-popup-announcement.md)
> 前端：`frontend/src/components/AnnouncementHost.tsx`（弹窗）、`pages/AnnouncementPage.tsx`（回看页）
> 发布入口：Django 后台「全站弹窗公告」

一条公告 = 一次「全站弹窗 + 站内通知 +（可选）邮件」。**没有对外写接口**：发布、编辑、
下线、看已读都在后台（`/admin/announcements/announcement/`），前台只读。

## 受众

| 值 | 含义 | 谁能看到 |
|---|---|---|
| `all` | 全站 | 任何人（含未登录访客） |
| `registered` | 注册用户 | 已登录账号 |
| `verified` | 认证用户 | `is_verified(user)` 为真（任一认证通道 approved 且未过期） |
| `admin` | 管理员 | `is_staff` 且委任通道未过期，或超级管理员 |

「推送站内通知」的收件人恒为**启用状态的账号**（`is_active=True`）中属于该受众者；
匿名访客只能看到 `all` 受众的弹窗，不产生通知与已读记录。

## GET /announcements/active/

匿名可访问。返回当前用户**还没读过**的在线公告（已发布、已到发布时刻、未过下线时间、
在受众内），按发布时间正序，最多 5 条。

```json
{
  "count": 1,
  "results": [
    {
      "id": 12,
      "title": "关于秋季摄影展报名的通知",
      "summary": "请各班宣传委员于本周五前提交名单。",
      "audience": "all",
      "audience_label": "全站（含未登录访客）",
      "has_document": true,
      "document_kind": "pdf",
      "document_name": "秋季摄影展通知.pdf",
      "document_size": 486213,
      "file_url": "/announcements/12/file/",
      "published_at": "2026-10-24T09:00:00+08:00",
      "expires_at": null,
      "read_at": null,
      "created_at": "2026-10-24T08:58:11+08:00"
    }
  ]
}
```

- `read_at` 只对登录用户有意义；未登录恒为 `null`。
- 已读判定走服务端台账（`announcements_announcementread`），跨设备一致；匿名访客由前端
  用 `localStorage["cobalt:announcement-seen"]` 记「已看过」。
- 弹窗关闭**不重取**本接口：宿主一次性取回队列，逐条弹完。

## GET /announcements/{id}/

匿名可访问，但按受众鉴权：不在受众内 / 未发布 / 已下线 → **404**（不泄露是否存在）。
用于站内通知点击回看（`payload.url = /announcements/{id}`，前端路由 `/#/announcements/{id}`）。

## POST /announcements/{id}/read/

需要登录（匿名 401/403）。幂等：重复调用返回 `already_read: true`。

```json
{ "read_at": "2026-10-24T09:03:22+08:00", "already_read": false }
```

打开详情页也会自动调用一次（查看即已读）。

## GET /announcements/{id}/file/

文档原件（PDF / .docx），鉴权规则同详情。响应头：

- `Content-Type`：`application/pdf` 或 `.docx` 的 MIME；
- `Content-Disposition: inline`（PDF 可被 pdf.js 直接取，`download` 属性仍可下载）；
- `Cache-Control: private, max-age=60`——**不能**用公共缓存：受众=管理员的公告不能被
  中间代理缓存给其他人；
- 不走 `/media/` 直链，避免绕过受众鉴权。

## 后台（不是 API）

`AnnouncementAdmin` 覆写了 `has_*_permission`：**只有一个权限**
`announcements.manage_announcements` 决定能否进入本模块（列表 / 新增 / 编辑 / 删除 /
已读明细），不授则仅超级管理员可用。迁移 `announcements/0002` 默认授予「社长」「信息组」。

- 保存时状态为「已发布」且 `published_at` 为空 → 立刻推送（`services.publish`）；
- 已发布过的公告再保存不会重复推送（`published_at` 非空即幂等返回）；
- 批量动作：「发布所选公告」「下线所选公告」；
- 「统计」栏显示受众数 / 已读人数 / 阅读率 / 邮件入队与送达数，并链接到**已读明细**
  （`/admin/announcements/announcement/<id>/reads/`：逐人列出已读时间或「未读」）；
- 邮件只发给**已认证邮箱**（`EmailChannel.is_available`），投递走通知队列（可重试）。

## 通知载荷

发布时对每位收件人写一条 `messaging.Notification(category="announcement", event="published")`：

```json
{
  "announcement_id": 12,
  "title": "关于秋季摄影展报名的通知",
  "url": "/announcements/12",
  "audience": "all",
  "file_kind": "pdf",
  "summary": "请各班宣传委员于本周五前提交名单。"
}
```

前端据此把通知标题显示为公告标题，点击进入 `/#/announcements/12`；邮件主题为
`【南汇一中传媒社】<公告标题>`，正文含摘要与回看链接。
