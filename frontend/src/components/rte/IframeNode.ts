import { Node, mergeAttributes } from "@tiptap/core";

type IframeAttrs = { src: string; title?: string | null };

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    iframe: {
      /** 在光标处插入一个 iframe 嵌入节点（用户粘的 raw iframe，经 parseIframeEmbed 解析）。 */
      insertIframe: (attrs: IframeAttrs) => ReturnType;
    };
  }
}

// 与后端 common/rich_text.py::_IFRAME_SANDBOX 保持一致（前端预览用；服务端才是闸）。
// 故意不含 allow-top-navigation，防 top-nav 重定向钓鱼。
const IFRAME_SANDBOX = "allow-scripts allow-same-origin allow-popups allow-presentation";

/**
 * 通用 iframe 嵌入原子节点：渲染受控 <iframe>（统一 sandbox）。
 * src 只接 https；srcdoc / 用户给的 sandbox 由服务端 sanitize_html 兜底剥离并盖戳。
 */
export const Iframe = Node.create({
  name: "iframe",
  group: "block",
  atom: true,

  addAttributes() {
    return {
      src: { default: "" },
      title: { default: null },
    };
  },

  parseHTML() {
    return [
      {
        tag: "iframe",
        getAttrs: (el) => ({
          src: (el as HTMLElement).getAttribute("src") || "",
          title: (el as HTMLElement).getAttribute("title"),
        }),
      },
    ];
  },

  renderHTML({ node }) {
    const attrs: Record<string, string> = {
      src: String(node.attrs.src ?? ""),
      frameborder: "0",
      allow: "autoplay; fullscreen; picture-in-picture",
      sandbox: IFRAME_SANDBOX,
      loading: "lazy",
    };
    if (node.attrs.title) attrs.title = String(node.attrs.title);
    return ["iframe", mergeAttributes(attrs)];
  },

  addCommands() {
    return {
      insertIframe:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: "iframe", attrs }),
    };
  },
});
