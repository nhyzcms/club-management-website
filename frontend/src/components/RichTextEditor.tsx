import { useEditor, useEditorState, EditorContent } from "@tiptap/react";
import { BubbleMenu, FloatingMenu } from "@tiptap/react/menus";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Highlight from "@tiptap/extension-highlight";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import TextAlign from "@tiptap/extension-text-align";
import { TextStyle } from "@tiptap/extension-text-style";
import { Color } from "@tiptap/extension-color";
import CharacterCount from "@tiptap/extension-character-count";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import TiptapImage from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import { useRef, useState, type ReactNode } from "react";
import "./RichTextEditor.css";
// mammoth 经动态 import() 按需加载（见 importWord），并已 code-split 到独立 chunk。
import { Video } from "./rte/VideoNode";
import { Iframe } from "./rte/IframeNode";
import { parseIframeEmbed } from "../utils/iframeEmbed";

interface Props {
  content: string;
  onChange?: (html: string) => void;
  /** 字数统计回调（正文文本长度）。 */
  onStats?: (chars: number) => void;
  placeholder?: string;
  editable?: boolean;
  /** 写作区最小高度（px）。 */
  minHeight?: number;
  /**
   * 图片上传：传入即启用「插入图片」按钮；返回上传后的图片 URL。
   * 同时供 Word 导入上传内嵌图片。与具体后端解耦，由调用方实现。
   */
  imageUpload?: (file: File) => Promise<string>;
  /** 启用「导入 Word」(.docx → HTML) 按钮。 */
  wordImport?: boolean;
  /** 视频上传：传入即启用「上传视频」按钮；返回上传后的视频 URL（可带进度）。 */
  videoUpload?: (file: File, onProgress: (ratio: number) => void) => Promise<string>;
  /** 启用「插入网页 iframe」按钮（粘贴 <iframe> 嵌入代码，src 须为 https）。 */
  iframeEmbed?: boolean;
}

type EditorInstance = NonNullable<ReturnType<typeof useEditor>>;

/* 调色板：与后端 common/rich_text.py 的 hex 值白名单对齐（只发 #rrggbb）。 */
const TEXT_COLORS = ["#111827", "#64748b", "#dc2626", "#ea580c", "#ca8a04", "#16a34a", "#2563eb", "#9333ea"];
const HIGHLIGHT_COLORS = ["#fff3a3", "#bbf7d0", "#bfdbfe", "#fbcfe8", "#fed7aa", "#e9d5ff"];

/* 小图标（动作类按钮 + 对齐 / 高亮） */
const Icon = {
  image: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9.5" r="1.5" /><path d="M21 16l-5-5L5 20" />
    </svg>
  ),
  link: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
    </svg>
  ),
  doc: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h4" />
    </svg>
  ),
  video: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="14" height="14" rx="2" /><path d="M17 9l4-2v10l-4-2" />
    </svg>
  ),
  embed: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18" />
    </svg>
  ),
  highlight: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  ),
  alignLeft: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M3 10h12M3 14h18M3 18h12" />
    </svg>
  ),
  alignCenter: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M6 10h12M3 14h18M6 18h12" />
    </svg>
  ),
  alignRight: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M9 10h12M3 14h18M9 18h12" />
    </svg>
  ),
  alignJustify: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M3 10h18M3 14h18M3 18h18" />
    </svg>
  ),
};

/** 编辑器正文字数（character-count 扩展；缺省回退文本长度）。 */
const countChars = (editor: EditorInstance): number =>
  (editor.storage as unknown as { characterCount?: { characters: () => number } })
    .characterCount?.characters() ?? editor.getText().length;

/** 气泡菜单内容：选区快捷格式。useEditorState 订阅格式态（不随全组件重渲染刷新）。 */
const BubbleFormatBar = ({ editor, onAddLink }: { editor: EditorInstance; onAddLink: () => void }) => {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      strike: e.isActive("strike"),
      highlight: e.isActive("highlight"),
      link: e.isActive("link"),
    }),
  });
  const btn = (label: ReactNode, action: () => void, active: boolean, title: string) => (
    <button type="button" className={`rte-btn${active ? " active" : ""}`} title={title} aria-label={title} aria-pressed={active}
            onMouseDown={(e) => e.preventDefault()} onClick={action}>{label}</button>
  );
  return (
    <>
      {btn(<b>B</b>, () => editor.chain().focus().toggleBold().run(), state.bold, "加粗")}
      {btn(<i>I</i>, () => editor.chain().focus().toggleItalic().run(), state.italic, "斜体")}
      {btn(<u>U</u>, () => editor.chain().focus().toggleUnderline().run(), state.underline, "下划线")}
      {btn(<s>S</s>, () => editor.chain().focus().toggleStrike().run(), state.strike, "删除线")}
      {btn(Icon.highlight, () => editor.chain().focus().toggleHighlight().run(), state.highlight, "高亮")}
      <span className="rte-divider" />
      {btn(Icon.link, onAddLink, state.link, "插入 / 编辑链接")}
    </>
  );
};

/** 浮动菜单内容：空行块类型快速切换。 */
const FloatingBlockBar = ({ editor }: { editor: EditorInstance }) => {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      paragraph: e.isActive("paragraph") && !e.isActive("heading"),
      h1: e.isActive("heading", { level: 1 }),
      h2: e.isActive("heading", { level: 2 }),
      h3: e.isActive("heading", { level: 3 }),
      quote: e.isActive("blockquote"),
    }),
  });
  const btn = (label: ReactNode, action: () => void, active: boolean, title: string) => (
    <button type="button" className={`rte-btn${active ? " active" : ""}`} title={title} aria-label={title} aria-pressed={active}
            onMouseDown={(e) => e.preventDefault()} onClick={action}>{label}</button>
  );
  return (
    <>
      {btn("正文", () => editor.chain().focus().setParagraph().run(), state.paragraph, "正文")}
      {btn("H1", () => editor.chain().focus().toggleHeading({ level: 1 }).run(), state.h1, "标题 1")}
      {btn("H2", () => editor.chain().focus().toggleHeading({ level: 2 }).run(), state.h2, "标题 2")}
      {btn("H3", () => editor.chain().focus().toggleHeading({ level: 3 }).run(), state.h3, "标题 3")}
      {btn("“", () => editor.chain().focus().toggleBlockquote().run(), state.quote, "引用")}
    </>
  );
};

/** 调色板弹层：文字颜色（text）/ 高亮背景色（hl）。按钮防焦点丢失，选色后收回。 */
const SwatchPopover = ({ editor, kind }: { editor: EditorInstance; kind: "text" | "hl" }) => {
  const [open, setOpen] = useState(false);
  const colors = kind === "text" ? TEXT_COLORS : HIGHLIGHT_COLORS;
  const active = kind === "text" ? !!editor.getAttributes("textStyle").color : editor.isActive("highlight");

  const apply = (c: string | null) => {
    if (kind === "text") {
      if (c) editor.chain().focus().setColor(c).run();
      else editor.chain().focus().unsetColor().run();
    } else {
      if (c) editor.chain().focus().setHighlight({ color: c }).run();
      else editor.chain().focus().unsetHighlight().run();
    }
    setOpen(false);
  };

  return (
    <div className="rte-pop-wrap">
      <button
        type="button"
        className={`rte-btn${open || active ? " active" : ""}`}
        title={kind === "text" ? "文字颜色" : "高亮"}
        aria-label={kind === "text" ? "文字颜色" : "高亮"}
        aria-expanded={open}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setOpen((v) => !v)}
      >
        {kind === "text" ? <span className="rte-color-a">A</span> : Icon.highlight}
      </button>
      {open && (
        <>
          <div className="rte-pop-backdrop" onMouseDown={() => setOpen(false)} />
          <div className="rte-pop" onMouseDown={(e) => e.preventDefault()}>
            <div className="rte-pop-grid">
              {colors.map((c) => (
                <button
                  key={c}
                  type="button"
                  className="rte-swatch"
                  style={{ background: c }}
                  title={c}
                  aria-label={`颜色 ${c}`}
                  onClick={() => apply(c)}
                />
              ))}
            </div>
            <button type="button" className="rte-pop-clear" onClick={() => apply(null)}>
              {kind === "text" ? "恢复默认色" : "清除高亮"}
            </button>
          </div>
        </>
      )}
    </div>
  );
};

const Toolbar = ({
  editor,
  imageUpload,
  wordImport,
  videoUpload,
  iframeEmbed,
  importing,
  onInsertImage,
  onAddLink,
  onImportWord,
  onInsertVideoFile,
  onInsertIframe,
}: {
  editor: ReturnType<typeof useEditor>;
  imageUpload?: Props["imageUpload"];
  wordImport?: boolean;
  videoUpload?: Props["videoUpload"];
  iframeEmbed?: boolean;
  importing: boolean;
  onInsertImage: () => void;
  onAddLink: () => void;
  onImportWord: () => void;
  onInsertVideoFile: () => void;
  onInsertIframe: () => void;
}) => {
  if (!editor) return null;

  const btn = (label: ReactNode, action: () => void, active: boolean, title: string, disabled = false) => (
    <button
      type="button"
      className={`rte-btn${active ? " active" : ""}`}
      onClick={action}
      title={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled}
    >
      {label}
    </button>
  );

  const aBtn = (label: ReactNode, align: "left" | "center" | "right" | "justify", title: string) =>
    btn(label, () => editor!.chain().focus().setTextAlign(align).run(), editor!.isActive({ textAlign: align }), title);

  return (
    <div className="rte-toolbar">
      <div className="rte-group">
        {btn("↶", () => editor!.chain().focus().undo().run(), false, "撤销", !editor!.can().undo())}
        {btn("↷", () => editor!.chain().focus().redo().run(), false, "重做", !editor!.can().redo())}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        {btn("H1", () => editor!.chain().focus().toggleHeading({ level: 1 }).run(), editor!.isActive("heading", { level: 1 }), "标题 1")}
        {btn("H2", () => editor!.chain().focus().toggleHeading({ level: 2 }).run(), editor!.isActive("heading", { level: 2 }), "标题 2")}
        {btn("H3", () => editor!.chain().focus().toggleHeading({ level: 3 }).run(), editor!.isActive("heading", { level: 3 }), "标题 3")}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        {btn(<b>B</b>, () => editor!.chain().focus().toggleBold().run(), editor!.isActive("bold"), "加粗")}
        {btn(<i>I</i>, () => editor!.chain().focus().toggleItalic().run(), editor!.isActive("italic"), "斜体")}
        {btn(<u>U</u>, () => editor!.chain().focus().toggleUnderline().run(), editor!.isActive("underline"), "下划线")}
        {btn(<s>S</s>, () => editor!.chain().focus().toggleStrike().run(), editor!.isActive("strike"), "删除线")}
        {btn("</>", () => editor!.chain().focus().toggleCodeBlock().run(), editor!.isActive("codeBlock"), "代码块")}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        <SwatchPopover editor={editor} kind="hl" />
        <SwatchPopover editor={editor} kind="text" />
        {btn(<span>X<sub>2</sub></span>, () => editor!.chain().focus().toggleSubscript().run(), editor!.isActive("subscript"), "下标")}
        {btn(<span>X<sup>2</sup></span>, () => editor!.chain().focus().toggleSuperscript().run(), editor!.isActive("superscript"), "上标")}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        {aBtn(Icon.alignLeft, "left", "左对齐")}
        {aBtn(Icon.alignCenter, "center", "居中")}
        {aBtn(Icon.alignRight, "right", "右对齐")}
        {aBtn(Icon.alignJustify, "justify", "两端对齐")}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        {btn("• 列表", () => editor!.chain().focus().toggleBulletList().run(), editor!.isActive("bulletList"), "无序列表")}
        {btn("1. 列表", () => editor!.chain().focus().toggleOrderedList().run(), editor!.isActive("orderedList"), "有序列表")}
        {btn("☑ 待办", () => editor!.chain().focus().toggleTaskList().run(), editor!.isActive("taskList"), "待办列表")}
      </div>
      <span className="rte-divider" />
      <div className="rte-group">
        {btn("“ 引用", () => editor!.chain().focus().toggleBlockquote().run(), editor!.isActive("blockquote"), "引用")}
        {btn("— 分割线", () => editor!.chain().focus().setHorizontalRule().run(), false, "分割线")}
      </div>

      {(imageUpload || wordImport || videoUpload || iframeEmbed) && <span className="rte-spacer" />}
      <div className="rte-group rte-actions">
        {iframeEmbed && (
          <button type="button" className="rte-action" onClick={onInsertIframe} title="插入网页嵌入代码（<iframe>…</iframe>，src 须为 https）">
            {Icon.embed} 嵌入网页
          </button>
        )}
        {videoUpload && (
          <button type="button" className="rte-action" onClick={onInsertVideoFile} title="上传视频文件">
            {Icon.video} 上传视频
          </button>
        )}
        {imageUpload && (
          <button type="button" className="rte-action" onClick={onInsertImage} title="插入图片">{Icon.image} 图片</button>
        )}
        {imageUpload && (
          <button type="button" className="rte-action" onClick={onAddLink} title="插入链接">{Icon.link} 链接</button>
        )}
        {wordImport && (
          <button type="button" className="rte-action" onClick={onImportWord} disabled={importing} title="从 Word（.docx）文档导入">
            {Icon.doc} {importing ? "导入中…" : "导入 Word"}
          </button>
        )}
      </div>
    </div>
  );
};

export default function RichTextEditor({
  content,
  onChange,
  onStats,
  placeholder = "请输入内容…",
  editable = true,
  minHeight,
  imageUpload,
  wordImport,
  videoUpload,
  iframeEmbed,
}: Props) {
  const imageInput = useRef<HTMLInputElement>(null);
  const wordInput = useRef<HTMLInputElement>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState("");
  const [videoProgress, setVideoProgress] = useState<number | null>(null);
  // 用 ref 持有最新回调，避免 useEditor 闭包过期
  const onChangeRef = useRef(onChange); onChangeRef.current = onChange;
  const onStatsRef = useRef(onStats); onStatsRef.current = onStats;

  const editor = useEditor({
    // 注意：不要开 shouldRerenderOnTransaction —— React 菜单组件（BubbleMenu/FloatingMenu）
    // 每次渲染都会 dispatch 一次 updateOptions 事务，与“事务→整树重渲染”形成死循环（React #185）。
    // 需要实时状态的局部 UI 用 useEditorState 订阅（见 BubbleFormatBar / FloatingBlockBar）。
    extensions: [
      // link 由下方显式注册（自定义 target/_blank 等属性），避免与 StarterKit 内置的重复注册
      StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5, 6] }, link: false }),
      Link.configure({
        autolink: true,
        HTMLAttributes: { target: "_blank", rel: "noopener noreferrer nofollow" },
      }),
      Highlight.configure({ multicolor: true }),
      Subscript,
      Superscript,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      TextStyle,
      Color,
      CharacterCount,
      TaskList,
      TaskItem.configure({ nested: true }),
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,
      TiptapImage.configure({ inline: true }),
      Video,
      Iframe,
      Placeholder.configure({ placeholder }),
    ],
    content,
    editable,
    onCreate: ({ editor }) => {
      onChangeRef.current?.(editor.getHTML());
      onStatsRef.current?.(editor.getText().length);
    },
    onUpdate: ({ editor }) => {
      onChangeRef.current?.(editor.getHTML());
      onStatsRef.current?.(editor.getText().length);
    },
  });

  const insertImage = async (file: File | null) => {
    if (!file || !editor || !imageUpload) return;
    setErr("");
    try {
      const src = await imageUpload(file);
      editor.chain().focus().setImage({ src }).run();
    } catch (e: any) {
      setErr(e?.message || "图片上传失败");
    }
  };

  const addLink = () => {
    if (!editor) return;
    const href = window.prompt("输入链接地址（https://…）", "https://");
    if (href === null) return;
    if (href.trim() === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: href.trim() }).run();
  };

  const importWord = async (file: File | null) => {
    if (!file || !editor) return;
    if (editor.getText().trim() && !window.confirm("导入将替换当前正文内容，是否继续？")) {
      return;
    }
    setImporting(true);
    setErr("");
    try {
      const arrayBuffer = await file.arrayBuffer();
      // 动态导入 mammoth：只在真正导入时加载，避免膨胀主包
      const mod: any = await import("mammoth");
      const mammoth: any = mod.default ?? mod;
      // Word 内嵌图片：上传到后端换 http URL（与 bleach 白名单 http(s) 协议匹配）
      const opts: any = imageUpload
        ? {
            convertImage: mammoth.images.imgElement(async (image: any) => {
              const buf: ArrayBuffer = await image.readAsArrayBuffer();
              const ext = (image.contentType || "image/png").split("/")[1] || "png";
              const f = new File([buf], `image.${ext}`, { type: image.contentType || "image/png" });
              const src = await imageUpload(f);
              return { src };
            }),
          }
        : undefined;
      const result = await mammoth.convertToHtml({ arrayBuffer }, opts);
      editor.chain().focus().setContent(result.value || "").run();
      onChangeRef.current?.(editor.getHTML());
      onStatsRef.current?.(editor.getText().length);
    } catch (e: any) {
      setErr(e?.message || "Word 导入失败，请确认是 .docx 格式");
    } finally {
      setImporting(false);
    }
  };

  const insertVideoFile = async (file: File | null) => {
    if (!file || !editor || !videoUpload) return;
    setErr("");
    setVideoProgress(null);
    try {
      const src = await videoUpload(file, setVideoProgress);
      editor.chain().focus().insertVideo({ src }).run();
    } catch (e: any) {
      setErr(e?.message || "视频上传失败");
    } finally {
      setVideoProgress(null);
    }
  };

  const insertIframe = () => {
    if (!editor) return;
    const raw = window.prompt("粘贴网页嵌入代码（<iframe>…</iframe>；src 须为 https://）", "");
    if (raw === null) return;
    const parsed = parseIframeEmbed(raw);
    if (!parsed) {
      setErr("无法识别：请粘贴包含 <iframe> 的嵌入代码，且 src 须为 https://");
      return;
    }
    setErr("");
    editor.chain().focus().insertIframe(parsed).run();
  };

  if (!editable) {
    return (
      <div className="rte-readonly">
        {editor && <EditorContent editor={editor} />}
      </div>
    );
  }

  return (
    <div className="rte-wrapper" style={minHeight ? ({ ["--rte-min-height" as any]: `${minHeight}px` }) : undefined}>
      <Toolbar
        editor={editor}
        imageUpload={imageUpload}
        wordImport={wordImport}
        videoUpload={videoUpload}
        iframeEmbed={iframeEmbed}
        importing={importing}
        onInsertImage={() => imageInput.current?.click()}
        onAddLink={addLink}
        onImportWord={() => wordInput.current?.click()}
        onInsertVideoFile={() => videoInput.current?.click()}
        onInsertIframe={insertIframe}
      />

      {/* 选区快捷格式：选中文字时浮出（位置用插件默认 top / offset 8） */}
      {editor && (
        <BubbleMenu
          editor={editor}
          updateDelay={80}
          shouldShow={({ editor: ed, state }) =>
            !state.selection.empty &&
            !ed.isActive("codeBlock") &&
            !("node" in state.selection)
          }
          className="rte-bubble"
        >
          <BubbleFormatBar editor={editor} onAddLink={addLink} />
        </BubbleMenu>
      )}

      {/* 空行浮出：快速切换块类型 */}
      {editor && (
        <FloatingMenu editor={editor} options={{ placement: "bottom-start", offset: 8 }} className="rte-float">
          <FloatingBlockBar editor={editor} />
        </FloatingMenu>
      )}

      <EditorContent editor={editor} className="rte-content" />
      {err && <div className="rte-err">{err}</div>}
      {videoProgress != null && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
          <span>视频上传 {Math.round(videoProgress * 100)}%</span>
          <div style={{ flex: 1, height: 6, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${Math.round(videoProgress * 100)}%`, height: "100%", background: "#2563eb", transition: "width .2s" }} />
          </div>
        </div>
      )}
      {editor && <div className="rte-foot"><span className="rte-count tnum">{countChars(editor)} 字</span></div>}
      <input
        ref={imageInput} type="file" accept="image/*" className="rte-file"
        onChange={(e) => { insertImage(e.target.files?.[0] ?? null); e.target.value = ""; }}
      />
      <input
        ref={wordInput} type="file" accept=".docx" className="rte-file"
        onChange={(e) => { importWord(e.target.files?.[0] ?? null); e.target.value = ""; }}
      />
      <input
        ref={videoInput} type="file" accept="video/*" className="rte-file"
        onChange={(e) => { insertVideoFile(e.target.files?.[0] ?? null); e.target.value = ""; }}
      />
    </div>
  );
}
