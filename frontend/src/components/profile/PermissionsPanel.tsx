import type { ReactNode } from "react";
import type { UserProfileData } from "../../types/profile";
import "../../styles/form.css";

const CAP_LABELS: Record<string, string> = {
  can_manage_news: "管理新闻",
  can_manage_tasks: "管理任务",
  can_assign_task: "指派任务",
  can_manage_tags: "管理标签",
  can_change_activity: "管理互动",
  can_view_feedback: "查看并了结反馈",
  can_handle_reports: "处理举报案",
  can_review_collections: "复审征集",
  can_edit_about: "编辑关于",
  can_manage_panoramas: "管理校园全景图",
  can_manage_exam: "管理考试看板",
  can_review_content: "审核内容",
  can_review_identity: "审核身份",
  can_force_publish: "免审发布",
  can_manage_comment_thread: "评论区协管",
  can_mute_user: "全站禁言",
  can_manage_announcement: "管理横幅公告",
  can_manage_announcements: "发布全站弹窗公告",
  can_review_password_reset: "审批密码重置",
};

/** 统一的 24x24 线性图标外壳，沿用项目内联 SVG 约定（stroke=currentColor）。 */
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

const CAP_ICONS: Record<string, ReactNode> = {
  can_manage_news: (
    <Svg>
      <rect x={4} y={3} width={16} height={18} rx={2} />
      <path d="M8 7h4" />
      <path d="M8 11h8" />
      <path d="M8 15h8" />
    </Svg>
  ),
  can_manage_tasks: (
    <Svg>
      <rect x={4} y={4} width={16} height={16} rx={2} />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </Svg>
  ),
  can_assign_task: (
    <Svg>
      <circle cx={9} cy={8} r={3.2} />
      <path d="M3.5 19a5.5 5.5 0 0 1 8-4.9" />
      <path d="M15 11h5" />
      <path d="M17.5 8.5L20 11l-2.5 2.5" />
    </Svg>
  ),
  can_manage_tags: (
    <Svg>
      <path d="M3 11V4.5a1.5 1.5 0 0 1 1.5-1.5H11l8.5 8.5a1.5 1.5 0 0 1 0 2.1l-5.4 5.4a1.5 1.5 0 0 1-2.1 0z" />
      <circle cx={7.5} cy={7.5} r={1.2} />
    </Svg>
  ),
  can_change_activity: (
    <Svg>
      <rect x={3} y={4} width={18} height={16} rx={2} />
      <path d="M3 9h18" />
      <path d="M8 14h2" />
      <path d="M14 14h2" />
    </Svg>
  ),
  can_view_feedback: (
    <Svg>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </Svg>
  ),
  can_handle_reports: (
    <Svg>
      <path d="M6 4h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
      <path d="M14 4v6h6" />
      <path d="M8 14h8" />
      <path d="M8 17h5" />
    </Svg>
  ),
  can_edit_about: (
    <Svg>
      <circle cx={12} cy={12} r={9} />
      <path d="M12 11v5" />
      <path d="M12 7.5h.01" />
    </Svg>
  ),
  can_manage_panoramas: (
    <Svg>
      <circle cx={12} cy={12} r={9} />
      <ellipse cx={12} cy={12} rx={3.6} ry={9} />
      <path d="M3.2 9.5h17.6" />
      <path d="M3.2 14.5h17.6" />
    </Svg>
  ),
  can_manage_exam: (
    <Svg>
      <rect x={4} y={3} width={16} height={18} rx={2} />
      <path d="M8 7h8" />
      <path d="M8 11h5" />
      <path d="M8 15h8" />
    </Svg>
  ),
  can_review_content: (
    <Svg>
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </Svg>
  ),
  can_review_identity: (
    <Svg>
      <rect x={3} y={5} width={18} height={14} rx={2} />
      <circle cx={9} cy={12} r={2.2} />
      <path d="M14 10h5" />
      <path d="M14 14h4" />
    </Svg>
  ),
  can_force_publish: (
    <Svg>
      <path d="M12 19V5" />
      <path d="M5 12l7-7 7 7" />
    </Svg>
  ),
  can_manage_comment_thread: (
    <Svg>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <path d="M8 8h8" />
      <path d="M8 12h5" />
    </Svg>
  ),
  can_mute_user: (
    <Svg>
      <circle cx={12} cy={12} r={8.5} />
      <path d="M8 8l8 8" />
    </Svg>
  ),
  can_manage_announcement: (
    <Svg>
      <path d="M4 10v4" />
      <path d="M4 12h3l9-5v10l-9-5H4z" />
      <path d="M18 9.5v5" />
    </Svg>
  ),
  can_manage_announcements: (
    <Svg>
      <rect x={3} y={5} width={18} height={14} rx={2.5} />
      <path d="M3 8h18" />
      <path d="M7 15h6" />
    </Svg>
  ),
  can_review_password_reset: (
    <Svg>
      <circle cx={8} cy={12} r={3.5} />
      <path d="M11.5 12H21" />
      <path d="M18 12v3" />
      <path d="M15 12v2" />
    </Svg>
  ),
};

export default function PermissionsPanel({ profile }: { profile: UserProfileData }) {
  const perms = profile.permissions ?? {};
  const groups = profile.groups ?? [];
  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">权限与角色</h2>
      <ul className="profile-perms">
        {Object.entries(CAP_LABELS).map(([key, label]) => (
          <li key={key} className="profile-perm">
            <span className="profile-perm-main">
              <span className="profile-perm-icon">{CAP_ICONS[key] ?? null}</span>
              <span>{label}</span>
            </span>
            <span className={"badge " + (perms[key] ? "badge-success" : "badge-ghost")}>
              {perms[key] ? "有" : "无"}
            </span>
          </li>
        ))}
      </ul>
      <p className="muted" style={{ marginTop: "var(--s-4)" }}>
        所属组：{groups.length ? groups.join("、") : "（无）"}
      </p>
    </div>
  );
}
