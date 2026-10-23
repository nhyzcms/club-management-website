import { Suspense, lazy } from "react";
import type { Announcement } from "../types/announcements";
import { formatDocumentSize } from "../types/announcements";
import PdfPreview from "./PdfPreview";

// docx-preview 体积不小，只有真正看 Word 公告时才加载。
const DocxPreview = lazy(() => import("./DocxPreview"));

/**
 * 公告的「原件」区：PDF 用 pdf.js、.docx 用 docx-preview，都按原排版渲染。
 *
 * 两种格式都同时提供「下载原件」——渲染器再保真也难免有字体缺失（服务器 / 手机没装的
 * 字体），原件是最终依据。
 */
export default function AnnouncementDocument({ item }: { item: Announcement }) {
  if (!item.has_document || !item.file_url) return null;
  const label = item.document_name || (item.document_kind === "pdf" ? "公告.pdf" : "公告.docx");
  const size = formatDocumentSize(item.document_size);

  return (
    <div className="ann-doc">
      {item.document_kind === "docx" ? (
        <Suspense fallback={<p className="ann-doc-note">正在加载 Word 预览…</p>}>
          <DocxPreview url={item.file_url} />
        </Suspense>
      ) : (
        <PdfPreview url={item.file_url} />
      )}
      <p className="ann-doc-foot">
        <a href={item.file_url} download={item.document_name || undefined}>
          下载原件（{label}{size ? ` · ${size}` : ""}）
        </a>
      </p>
    </div>
  );
}
