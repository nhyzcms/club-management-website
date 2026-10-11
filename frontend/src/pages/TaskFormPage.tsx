import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { taskApi } from "../api/tasks";
import { messagingApi } from "../api/messaging";
import {
  TaskDetail, TaskPriority, TaskFormData,
  Tag, PRIORITY_LABELS,
} from "../types/tasks";
import type { ThreadStatus } from "../types/messaging";
import RichTextEditor from "../components/RichTextEditor";
import UserSearchSelect, { type SelectUser } from "../components/UserSearchSelect";
import CommentThreadStatusField from "../components/CommentThreadStatusField";
import "./TaskFormPage.css";

// 任务详情返回的 TaskUser → 选择器最小形状
const toSelect = (u: { id: number; username: string; nickname: string; avatar: string | null }): SelectUser => ({
  id: u.id,
  username: u.username,
  nickname: u.nickname,
  avatar: u.avatar,
});

export default function TaskFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = !!id;

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assignee, setAssignee] = useState<SelectUser[]>([]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [collaborators, setCollaborators] = useState<SelectUser[]>([]);
  const [commentThreadStatus, setCommentThreadStatus] = useState<ThreadStatus>("open");

  const [tags, setTags] = useState<Tag[]>([]);

  useEffect(() => {
    taskApi.listTags().then((d) => setTags(d.results || d)).catch(console.error);
  }, []);

  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    taskApi.get(Number(id))
      .then((task: TaskDetail) => {
        if (task.status !== "pending") {
          setBlocked(true);
          return;
        }
        setTitle(task.title);
        setDescription(task.description);
        setPriority(task.priority);
        setAssignee(task.assignee ? [toSelect(task.assignee)] : []);
        setTagIds(task.tags.map((t) => t.id));
        setCollaborators(task.collaborators.map(toSelect));
        messagingApi.getThread({ task: task.id })
          .then((t) => setCommentThreadStatus(t.status))
          .catch(() => {});
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id, isEdit]);

  const toggleTag = (tagId: number) => {
    setTagIds((prev) =>
      prev.includes(tagId) ? prev.filter((x) => x !== tagId) : [...prev, tagId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("标题不能为空");
      return;
    }
    setSaving(true);
    setError("");

    const data: TaskFormData = {
      title: title.trim(),
      description,
      priority,
      comment_thread_status: commentThreadStatus,
    };
    if (assignee.length > 0) data.assignee_id = assignee[0].id;
    if (tagIds.length > 0) data.tag_ids = tagIds;
    if (collaborators.length > 0) data.collaborator_ids = collaborators.map((c) => c.id);

    try {
      const result = isEdit
        ? await taskApi.update(Number(id), data)
        : await taskApi.create(data);
      await messagingApi.applyHostThreadStatus({ task: result.id }, commentThreadStatus);
      navigate(`/tasks/${result.id}`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="task-page"><div className="task-loading">加载中…</div></div>;

  if (blocked) {
    return (
      <div className="task-page">
        <div className="task-form-container">
          <div className="task-error">该任务当前状态不可编辑</div>
          <button className="task-btn-secondary" onClick={() => navigate(`/tasks/${id}`)}>
            返回详情
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="task-page">
      <div className="task-form-container">
        <div className="task-detail-header">
          <button className="task-back" onClick={() => navigate(id ? `/tasks/${id}` : "/tasks")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5" /><path d="m12 19-7-7 7-7" />
            </svg>
            {isEdit ? "任务详情" : "任务列表"}
          </button>
        </div>

        <h1 className="task-form-title">{isEdit ? "编辑任务" : "新建任务"}</h1>

        {error && <div className="task-error">{error}</div>}

        <form onSubmit={handleSubmit} className="task-form">
          <div className="form-field">
            <label>标题 *</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="输入任务标题" maxLength={200} required />
          </div>

          <div className="form-field">
            <label>描述</label>
            <RichTextEditor content={description} onChange={setDescription} placeholder="详细描述任务内容…" />
          </div>

          <div className="form-row">
            <div className="form-field">
              <label>优先级</label>
              <select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
                {Object.entries(PRIORITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-field">
            <label>负责人</label>
            <UserSearchSelect selected={assignee} onChange={setAssignee} single placeholder="搜索并选择负责人（可选）" />
          </div>

          <div className="form-field">
            <label>标签</label>
            <div className="tag-selector">
              {tags.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`tag-option${tagIds.includes(t.id) ? " selected" : ""}`}
                  style={tagIds.includes(t.id) ? { backgroundColor: t.color, color: "#fff" } : { borderColor: t.color, color: t.color }}
                  onClick={() => toggleTag(t.id)}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>

          <div className="form-field">
            <label>协作者</label>
            <UserSearchSelect selected={collaborators} onChange={setCollaborators} placeholder="搜索并添加协作者（可多选）" />
          </div>

          <CommentThreadStatusField value={commentThreadStatus} onChange={setCommentThreadStatus} />

          <div className="form-actions">
            <button type="button" className="task-btn-secondary" onClick={() => navigate(id ? `/tasks/${id}` : "/tasks")}>
              取消
            </button>
            <button type="submit" className="task-btn-primary" disabled={saving}>
              {saving ? "保存中…" : isEdit ? "保存修改" : "创建任务"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
