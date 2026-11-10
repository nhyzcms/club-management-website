import { Link, useNavigate } from "react-router-dom";
import {
  TaskListItem,
  TaskStatus,
  STATUS_LABELS,
  STATUS_BADGE_CLASS,
  PRIORITY_DOT_CLASS,
} from "../types/tasks";
import "./TaskTimeline.css";
import Avatar from "./Avatar";

interface Props {
  tasks: TaskListItem[];
}

// 轨道圆点按状态着色（cobalt token；cobalt 调色板无紫色，reviewing/review 均映射为 warning）
const STATUS_DOT: Record<TaskStatus, string> = {
  pending: "var(--ink-400)",
  in_progress: "var(--brand-600)",
  reviewing: "var(--warning)",
  review: "var(--warning)",
  completed: "var(--success)",
  cancelled: "var(--ink-400)",
};

function formatShortDate(d: string) {
  return new Date(d).toLocaleDateString("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
}

function daysBetween(a: string, b: string): number {
  const ms = new Date(b).getTime() - new Date(a).getTime();
  return Math.max(1, Math.round(ms / (1000 * 60 * 60 * 24)));
}

export default function TaskTimeline({ tasks }: Props) {
  const navigate = useNavigate();

  const sorted = [...tasks].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <div className="timeline">
      {sorted.map((task) => {
        const isActive = task.status === "in_progress" || task.status === "review";

        let durationText: string;
        if (task.status === "completed" && task.completed_at) {
          durationText = `创建: ${formatShortDate(task.created_at)} → 完成: ${formatShortDate(task.completed_at)} (${daysBetween(task.created_at, task.completed_at)} 天)`;
        } else if (isActive) {
          const days = daysBetween(task.created_at, new Date().toISOString());
          durationText = `创建: ${formatShortDate(task.created_at)} → 进行中 (已持续 ${days} 天)`;
        } else {
          durationText = `创建: ${formatShortDate(task.created_at)}`;
        }

        return (
          <div
            key={task.id}
            className="timeline-item"
            onClick={() => navigate(`/tasks/${task.id}`)}
          >
            <div className="timeline-dot-wrap">
              <span
                className={`timeline-dot${isActive ? " pulse" : ""}`}
                style={{ backgroundColor: STATUS_DOT[task.status] }}
              />
            </div>
            <div className="timeline-card">
              <div className="timeline-card-head">
                <span className={"prio-dot " + PRIORITY_DOT_CLASS[task.priority]} />
                <span className="tc-title">{task.title}</span>
                <span className={"badge " + STATUS_BADGE_CLASS[task.status]}>
                  {STATUS_LABELS[task.status]}
                </span>
              </div>
              <div className="timeline-card-meta">
                <span className="timeline-assignee">
                  {task.assignee && <Link to={`/u/${task.assignee.id}`}><Avatar user={task.assignee} /></Link>}
                  {task.assignee?.nickname || task.assignee?.username || "未分配"}
                </span>
                {task.tags.map((t) => (
                  <span key={t.id} className="tag-mini">{t.name}</span>
                ))}
              </div>
              <div className="timeline-duration">{durationText}</div>
            </div>
          </div>
        );
      })}
      {sorted.length === 0 && (
        <div className="timeline-empty">暂无任务</div>
      )}
    </div>
  );
}
