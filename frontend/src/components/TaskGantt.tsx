import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Gantt from "frappe-gantt";
import { TaskListItem, STATUS_LABELS } from "../types/tasks";
import "./TaskGantt.css";

interface Props {
  tasks: TaskListItem[];
}

const STATUS_ORDER: Record<string, number> = {
  in_progress: 0,
  review: 1,
  pending: 2,
  completed: 3,
  cancelled: 4,
};

// 甘特条/图例颜色取自 cobalt token（cobalt 无紫色，reviewing/review 均映射 warning）
const STATUS_TOKEN: Record<string, string> = {
  pending: "--ink-400",
  in_progress: "--brand-600",
  reviewing: "--warning",
  review: "--warning",
  completed: "--success",
  cancelled: "--ink-400",
};

function tokenColor(token: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

function statusToProgress(status: string): number {
  if (status === "completed") return 100;
  if (status === "in_progress" || status === "review") return 50;
  return 0;
}

function toDateStr(d: string): string {
  return d.split("T")[0];
}

export default function TaskGantt({ tasks }: Props) {
  const navigate = useNavigate();
  const svgRef = useRef<SVGSVGElement>(null);
  const ganttRef = useRef<Gantt | null>(null);
  const tasksRef = useRef<TaskListItem[]>([]);
  const [viewMode, setViewMode] = useState<string>("Day");

  const sorted = [...tasks].sort((a, b) => {
    const sa = STATUS_ORDER[a.status] ?? 99;
    const sb = STATUS_ORDER[b.status] ?? 99;
    if (sa !== sb) return sa - sb;
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });

  useEffect(() => {
    if (!svgRef.current || sorted.length === 0) return;

    const ganttTasks = sorted.map((task) => ({
      id: String(task.id),
      name: task.title,
      start: toDateStr(task.created_at),
      end: task.completed_at
        ? toDateStr(task.completed_at)
        : toDateStr(new Date().toISOString()),
      progress: statusToProgress(task.status),
      dependencies: "",
    }));

    if (ganttRef.current) {
      ganttRef.current.tasks = ganttTasks as any;
      ganttRef.current.refresh();
    } else {
      ganttRef.current = new Gantt(svgRef.current, ganttTasks as any, {
        view_mode: "Day",
        readonly: true,
        popup: () => false,
        on_click: (task: any) => {
          const id = Number(task.id);
          if (id) navigate(`/tasks/${id}`);
        },
      });
    }

    tasksRef.current = sorted;
    applyBarColors(sorted);

    return () => {
      if (svgRef.current) {
        svgRef.current.innerHTML = "";
      }
      ganttRef.current = null;
    };
  }, [tasks]);

  const applyBarColors = (taskList: TaskListItem[]) => {
    if (!svgRef.current) return;
    const bars = svgRef.current.querySelectorAll(".bar-wrapper");
    bars.forEach((bar, i) => {
      if (i < taskList.length) {
        const color = tokenColor(STATUS_TOKEN[taskList[i].status] || "--ink-400");
        const barEl = bar.querySelector(".bar") as SVGElement;
        if (barEl && color) {
          barEl.setAttribute("fill", color);
          barEl.setAttribute("style", `fill: ${color};`);
        }
      }
    });
  };

  const handleViewModeChange = (mode: string) => {
    setViewMode(mode);
    if (ganttRef.current) {
      ganttRef.current.change_view_mode(mode);
      applyBarColors(tasksRef.current);
    }
  };

  if (tasks.length === 0) {
    return <div className="gantt-empty">暂无任务</div>;
  }

  return (
    <div className="gantt-wrapper">
      <div className="gantt-controls">
        {["Day", "Week", "Month"].map((mode) => (
          <button
            key={mode}
            className={"gantt-mode-btn" + (viewMode === mode ? " active" : "")}
            onClick={() => handleViewModeChange(mode)}
          >
            {{ Day: "日", Week: "周", Month: "月" }[mode]}
          </button>
        ))}
      </div>
      <div className="gantt-legend">
        {(["in_progress", "review", "pending", "completed", "cancelled"] as const).map((s) => (
          <span key={s} className="gantt-legend-item">
            <span
              className="gantt-legend-dot"
              style={{ backgroundColor: `var(${STATUS_TOKEN[s]})` }}
            />
            {STATUS_LABELS[s]}
          </span>
        ))}
      </div>
      <svg ref={svgRef} className="gantt-svg" />
    </div>
  );
}
