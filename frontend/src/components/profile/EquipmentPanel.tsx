import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import "../../styles/profile.css";

/**
 * 个人中心 →「我的设备」（2026-11-10）。
 *
 * 社员登记自己能带到社团活动使用的器材（相机、电脑、配件等），只填物品名。
 * 只有「已绑定社员身份」的账号能进入本面板（入口由 UserProfile 按 viewer.is_member 控制），
 * 数据只有本人和管理员可见；每人最多 30 项。
 */
interface EquipmentItem {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

const LIMIT = 30;
const NAME_MAX = 100;

const fmtDate = (iso: string): string => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export default function EquipmentPanel() {
  const [items, setItems] = useState<EquipmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = () => {
    setLoading(true);
    api.memberEquipment()
      .then((d: any) => setItems(Array.isArray(d?.items) ? d.items : []))
      .catch((e: any) => setError(e.message || "加载失败"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const flash = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(""), 3000);
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    const value = name.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.addMemberEquipment(value);
      setName("");
      flash("已添加");
      load();
    } catch (err: any) {
      setError(err.message || "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (item: EquipmentItem) => {
    setEditingId(item.id);
    setDraft(item.name);
    setError("");
  };

  const saveEdit = async (id: number) => {
    const value = draft.trim();
    if (!value) {
      setError("物品名不能为空。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.renameMemberEquipment(id, value);
      setEditingId(null);
      flash("已保存");
      load();
    } catch (err: any) {
      setError(err.message || "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: EquipmentItem) => {
    if (!window.confirm(`删除「${item.name}」？`)) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteMemberEquipment(item.id);
      flash("已删除");
      load();
    } catch (err: any) {
      setError(err.message || "删除失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">我的设备</h2>
      <p className="muted equip-intro">
        登记你能带到社团活动使用的设备，例如相机、镜头、三脚架、笔记本电脑、存储卡等。
        信息只有你自己和管理员能看到，方便活动前统一调配。
      </p>

      {notice && <div className="alert alert-success" role="status"><span>{notice}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}

      <form className="equip-add" onSubmit={add}>
        <input
          className="input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={NAME_MAX}
          placeholder="物品名，例如：佳能 EOS R6 相机"
          aria-label="物品名"
          disabled={busy || items.length >= LIMIT}
        />
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !name.trim() || items.length >= LIMIT}
        >
          添加
        </button>
      </form>
      <p className="hint equip-count">已登记 {items.length} / {LIMIT} 项</p>

      {loading ? (
        <p className="muted">加载中…</p>
      ) : items.length === 0 ? (
        <p className="muted">还没有登记设备。填写上面的物品名并点「添加」即可。</p>
      ) : (
        <ul className="equip-list">
          {items.map((item) => (
            <li className="equip-row" key={item.id}>
              {editingId === item.id ? (
                <>
                  <input
                    className="input equip-edit"
                    type="text"
                    value={draft}
                    maxLength={NAME_MAX}
                    onChange={(e) => setDraft(e.target.value)}
                    aria-label="修改物品名"
                    autoFocus
                  />
                  <div className="equip-actions">
                    <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => saveEdit(item.id)}>
                      保存
                    </button>
                    <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={() => setEditingId(null)}>
                      取消
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="equip-main">
                    <span className="equip-name">{item.name}</span>
                    <span className="muted equip-time">更新于 {fmtDate(item.updated_at)}</span>
                  </div>
                  <div className="equip-actions">
                    <button className="btn btn-secondary btn-sm" type="button" disabled={busy} onClick={() => startEdit(item)}>
                      编辑
                    </button>
                    <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={() => remove(item)}>
                      删除
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
