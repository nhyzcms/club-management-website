import { Node, mergeAttributes } from "@tiptap/core";

type VideoAttrs = { src: string };

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    video: {
      /** 在光标处插入一个视频节点（本地上传）。外链嵌入已拆为独立 Iframe 节点（见 IframeNode）。 */
      insertVideo: (attrs: VideoAttrs) => ReturnType;
    };
  }
}

/**
 * 视频原子节点（本地上传）：渲染 <video src controls preload="metadata">。
 * renderHTML 手控输出；外链 iframe 嵌入由独立的 Iframe 节点承载。
 */
export const Video = Node.create({
  name: "video",
  group: "block",
  atom: true,

  addAttributes() {
    return {
      src: { default: "" },
    };
  },

  parseHTML() {
    return [
      {
        tag: "video",
        getAttrs: (el) => ({ src: (el as HTMLElement).getAttribute("src") || "" }),
      },
    ];
  },

  renderHTML({ node }) {
    return ["video", mergeAttributes({ src: String(node.attrs.src ?? ""), controls: "controls", preload: "metadata" })];
  },

  addCommands() {
    return {
      insertVideo:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: "video", attrs }),
    };
  },
});
