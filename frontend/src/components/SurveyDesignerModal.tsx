import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SurveyCreator, SurveyCreatorComponent } from "survey-creator-react";
import "survey-core/survey-core.css";
import "survey-creator-core/survey-creator-core.css";
import { SURVEY_LOCALE } from "../utils/surveyCreatorLocale";
import { EMPTY_SURVEY_SCHEMA, type SurveySchema } from "../utils/surveySchema";

/**
 * 问卷设计弹层（SurveyJS Creator）。
 *
 * 为什么是弹层而不是内嵌进表单：
 * - 活动表单本身是 `<form>`，Creator 内部有大量 input / button，内嵌会误触发表单提交；
 * - Creator 体积大（survey-creator-*），由调用方 `React.lazy` 加载，只在打开时才下载；
 * - 通过 portal 挂到 `document.body`，与表单 DOM 完全隔离。
 *
 * 用法：调用方持有 Schema 状态，点「完成」时拿到整份 Schema，随活动一起提交。
 */
export default function SurveyDesignerModal({
  initial,
  title,
  onCancel,
  onApply,
}: {
  /** 打开时的既有 Schema；为空则给一页空问卷。 */
  initial: SurveySchema | null;
  title: string;
  onCancel: () => void;
  onApply: (schema: SurveySchema) => void;
}) {
  const [creator, setCreator] = useState<SurveyCreator | null>(null);
  const [error, setError] = useState("");
  const initialRef = useRef<SurveySchema>(initial ?? EMPTY_SURVEY_SCHEMA);
  // 用户是否真的动过设计稿：不能用「JSON 与初始值不同」来判断，
  // Creator 载入时会补默认字段（规范化），那样一打开就会被误判成「有改动」。
  const dirtyRef = useRef(false);
  const cancelRef = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true;
    try {
      const c = new SurveyCreator({ showLogicTab: true, locale: SURVEY_LOCALE });
      // 工具栏不显示「保存」——落库由弹层的「完成」+ 活动表单的提交按钮统一负责。
      c.showSaveButton = false;
      c.JSON = initialRef.current;
      // 先赋值 JSON 再挂监听，避免载入本身触发「已修改」。
      c.onModified.add(() => {
        dirtyRef.current = true;
      });
      if (alive) setCreator(c);
      return () => {
        alive = false;
        c.dispose();
      };
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "问卷编辑器加载失败");
      return () => {
        alive = false;
      };
    }
  }, []);

  // 弹层打开期间锁住页面滚动，Esc 关闭（与「取消」同一路径，含未应用改动的确认）。
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") cancelRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const apply = () => {
    if (!creator) return;
    onApply(creator.JSON as SurveySchema);
  };

  const cancel = () => {
    // 真的改过但没点「完成」时确认一次，避免误关丢掉设计稿。
    if (dirtyRef.current && !window.confirm("问卷改动尚未应用，确定放弃这些修改吗？")) return;
    onCancel();
  };
  cancelRef.current = cancel;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 12,
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          width: "min(1280px, 100%)",
          height: "min(92vh, 100%)",
          background: "var(--bg)",
          borderRadius: 10,
          boxShadow: "0 12px 40px rgba(0,0,0,0.3)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
            padding: "10px 16px",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <strong style={{ fontSize: 16 }}>{title}</strong>
          <span style={{ color: "var(--muted)", fontSize: 12 }}>
            从左侧题型拖拽（或点选）到画布添加题目；完成后回填到活动表单，随活动一起保存。
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={cancel}>取消</button>
            <button type="button" className="btn btn-primary btn-sm" onClick={apply} disabled={!creator}>
              完成
            </button>
          </div>
        </header>
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
          {error && (
            <div className="alert alert-danger" style={{ margin: 16 }}>
              <span>{error}</span>
            </div>
          )}
          {creator && (
            <div style={{ height: "100%" }}>
              <SurveyCreatorComponent creator={creator} />
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
