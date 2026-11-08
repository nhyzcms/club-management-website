import { useState } from "react";
import type { PostcardPortal, RegisterResult } from "../../api/postcard";
import { postcardApi } from "../../api/postcard";
import { useTurnstile } from "../../turnstile";
import BarcodeScanPanel from "./BarcodeScanPanel";
import SchoolPicker from "./SchoolPicker";
import {
  addBarcode,
  buildRegisterFormData,
  checkPhotoFile,
  validateRegistration,
  type DraftItem,
  type RegisterFormValues,
} from "./pure";

interface Props {
  portal: PostcardPortal;
  fingerprint: string;
  isMobile: boolean;
  onRegistered: (result: RegisterResult) => void;
}

const EMPTY_VALUES: RegisterFormValues = {
  sender_name: "",
  grade: "",
  class_no: "",
  dest_region: "",
  dest_school: "",
};

/**
 * 明信片登记表单：扫码/手填条码（≤5 张，每张正反两面照片）+ 寄出人信息 +
 * 寄达区/校下拉 + Turnstile。提交走 multipart（后端 RegisterView 契约）。
 */
export default function RegisterForm({ portal, fingerprint, isMobile, onRegistered }: Props) {
  const [values, setValues] = useState<RegisterFormValues>(EMPTY_VALUES);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [manualCode, setManualCode] = useState("");
  const [error, setError] = useState("");
  const [itemError, setItemError] = useState("");
  const [busy, setBusy] = useState(false);
  const { containerRef, token, reset, enabled } = useTurnstile(true);

  const setField = (key: keyof RegisterFormValues, value: string) => {
    setValues((v) => {
      const next = { ...v, [key]: value };
      // 换区后原寄达校大概率不在新区的清单里，清空避免提交被拒
      if (key === "dest_region") next.dest_school = "";
      return next;
    });
  };

  const handleCode = (raw: string) => {
    const result = addBarcode(items, raw);
    if (result.ok) {
      setItems(result.items);
      setItemError("");
    } else {
      setItemError(result.reason);
    }
  };

  const setPhoto = (index: number, side: "front" | "back", file: File | null) => {
    if (file) {
      const problem = checkPhotoFile(file);
      if (problem) {
        setItemError(`第 ${index + 1} 张明信片${side === "front" ? "正面" : "反面"}照片：${problem}`);
        return;
      }
    }
    setItemError("");
    setItems((list) =>
      list.map((it, i) => (i === index ? { ...it, [side]: file } : it)),
    );
  };

  const removeItem = (index: number) => {
    setItems((list) => list.filter((_, i) => i !== index));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const problem = validateRegistration(values, items);
    if (problem) {
      setError(problem);
      return;
    }
    if (enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await postcardApi.register(
        buildRegisterFormData(values, items, fingerprint, token),
      );
      setValues(EMPTY_VALUES);
      setItems([]);
      setManualCode("");
      reset();
      onRegistered(result);
    } catch (err: any) {
      setError(err?.message || "登记失败，请稍后重试。");
      reset();
    } finally {
      setBusy(false);
    }
  };

  const primaryBtn = isMobile ? "m-btn-primary" : "btn btn-primary";
  const ghostBtn = isMobile ? "m-btn-ghost" : "btn btn-ghost";

  return (
    <form className="pc-form" onSubmit={submit} noValidate>
      {error && (
        <div className="alert alert-danger" role="alert">
          <span>{error}</span>
        </div>
      )}

      <div className="pc-field-grid">
        <div className="pc-field">
          <label className="label" htmlFor="pc-name">姓名</label>
          <input
            id="pc-name"
            className="input"
            value={values.sender_name}
            maxLength={64}
            autoComplete="off"
            placeholder="寄出人姓名"
            onChange={(e) => setField("sender_name", e.target.value)}
          />
        </div>
        <div className="pc-field">
          <label className="label" htmlFor="pc-grade">年级</label>
          <select
            id="pc-grade"
            className="input"
            value={values.grade}
            onChange={(e) => setField("grade", e.target.value)}
          >
            <option value="">请选择</option>
            {portal.grades.map((g) => (
              <option key={g.value} value={g.value}>{g.label}</option>
            ))}
          </select>
        </div>
        <div className="pc-field">
          <label className="label" htmlFor="pc-class">班级</label>
          <select
            id="pc-class"
            className="input"
            value={values.class_no}
            onChange={(e) => setField("class_no", e.target.value)}
          >
            <option value="">请选择</option>
            {portal.classes.map((c) => (
              <option key={c} value={String(c)}>{c} 班</option>
            ))}
          </select>
        </div>
        <div className="pc-field">
          <label className="label" htmlFor="pc-region">寄达区</label>
          <select
            id="pc-region"
            className="input"
            value={values.dest_region}
            onChange={(e) => setField("dest_region", e.target.value)}
          >
            <option value="">请选择</option>
            {portal.regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div className="pc-field pc-field-wide">
          <label className="label" htmlFor="pc-school">寄达校</label>
          <SchoolPicker
            id="pc-school"
            schools={portal.schools}
            region={values.dest_region}
            value={values.dest_school}
            onChange={(name) => setField("dest_school", name)}
          />
        </div>
      </div>

      <div className="pc-items-head">
        <h3>明信片（{items.length}/5）</h3>
        <p className="muted">一条码对应一份明信片；一人可寄多份，一次最多 5 张。</p>
      </div>

      <BarcodeScanPanel onCode={handleCode} />

      <div className="pc-manual-add">
        <input
          className="input"
          inputMode="numeric"
          autoComplete="off"
          maxLength={7}
          placeholder="或手动输入 7 位条码号"
          value={manualCode}
          onChange={(e) => setManualCode(e.target.value.replace(/[^\d]/g, ""))}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleCode(manualCode);
              setManualCode("");
            }
          }}
        />
        <button
          type="button"
          className={ghostBtn}
          disabled={!manualCode.trim()}
          onClick={() => {
            handleCode(manualCode);
            setManualCode("");
          }}
        >
          添加
        </button>
      </div>

      {itemError && <p className="pc-item-error">{itemError}</p>}

      {items.length === 0 && (
        <p className="muted pc-items-empty">还没有添加明信片——扫码或输入条码号后，为每张上传正、反两面照片。</p>
      )}

      <ul className="pc-item-list">
        {items.map((it, i) => (
          <li key={it.barcode} className="pc-item">
            <div className="pc-item-bar">
              <span className="pc-item-code tnum">{it.barcode}</span>
              <button type="button" className={ghostBtn} onClick={() => removeItem(i)}>
                移除
              </button>
            </div>
            <div className="pc-item-photos">
              {(["front", "back"] as const).map((side) => {
                const file = it[side];
                return (
                  <label key={side} className={"pc-photo" + (file ? " has-file" : "")}>
                    <input
                      type="file"
                      accept="image/*"
                      onChange={(e) => setPhoto(i, side, e.target.files?.[0] || null)}
                    />
                    {file ? (
                      <img src={URL.createObjectURL(file)} alt={`${side === "front" ? "正面" : "反面"}照片预览`} />
                    ) : (
                      <span>{side === "front" ? "＋ 正面照片" : "＋ 反面照片"}</span>
                    )}
                    <em>{side === "front" ? "正面" : "反面"}</em>
                  </label>
                );
              })}
            </div>
          </li>
        ))}
      </ul>

      {enabled && <div ref={containerRef} className="pc-turnstile" />}

      <button type="submit" className={primaryBtn + " pc-submit"} disabled={busy}>
        {busy ? "提交中…" : `提交登记（${items.length} 张）`}
      </button>
      <p className="muted pc-form-hint">
        提交后经 AI 审核：通过后生成 6 位登记码并自动删除照片；AI 暂不可用时转人工
        复核，登记码立即生成。登记码是查看和修改登记记录的唯一凭证，请妥善保存。
      </p>
    </form>
  );
}
