import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/**
 * 活动表单：调研问卷「发起前即可设计」的回归测试。
 *
 * 之前的 bug：表单里只能设置标题/受众/截止，问卷必须等创建后到详情页的
 * 「编辑问卷」里补题，导致「先排期待开始 → 再补题目」只能分两步走。
 *
 * 这里把 SurveyJS Creator 弹层整体 mock 掉（它体积大、在 jsdom 里跑不动），
 * 只验证表单侧的接线：弹层「完成」回填 schema → 提交时随活动一起发给后端。
 */

const { createMock, getMock } = vi.hoisted(() => ({
  createMock: vi.fn(() => Promise.resolve({ id: 99 })),
  getMock: vi.fn(),
}));

vi.mock("../../api/activities", () => ({
  activityApi: {
    create: createMock,
    get: getMock,
    update: vi.fn(() => Promise.resolve({ id: 99 })),
    uploadImage: vi.fn(() => Promise.resolve({ url: "/media/x.png" })),
  },
}));
vi.mock("../../api/messaging", () => ({
  messagingApi: {
    getThread: vi.fn(() => Promise.resolve({ status: "open" })),
    applyHostThreadStatus: vi.fn(() => Promise.resolve({})),
  },
}));
vi.mock("../../api/sitePolicy", () => ({
  useSitePolicy: () => ({ sync_upload_max_bytes: 20 * 1024 * 1024 }),
}));
vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../../components/RichTextEditor", () => ({
  default: ({ onChange }: { onChange: (v: string) => void }) => (
    <textarea aria-label="正文说明" onChange={(e) => onChange(e.target.value)} />
  ),
}));
// 弹层 mock：一个按钮把「1 道题」的 Schema 回填给表单。
vi.mock("../../components/SurveyDesignerModal", () => ({
  default: ({
    title,
    onApply,
  }: {
    title: string;
    onApply: (schema: Record<string, unknown>) => void;
  }) => (
    <div role="dialog" aria-label={title}>
      <button
        type="button"
        onClick={() =>
          onApply({ title: "", pages: [{ name: "page1", elements: [{ type: "text", name: "q1" }] }] })
        }
      >
        模拟完成设计
      </button>
    </div>
  ),
}));

import ActivityFormPage from "../ActivityFormPage";

const ONE_QUESTION_SCHEMA = {
  title: "",
  pages: [{ name: "page1", elements: [{ type: "text", name: "q1" }] }],
};

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/activity/new" element={<ActivityFormPage />} />
        <Route path="/activity/:id/edit" element={<ActivityFormPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ActivityFormPage · 调研问卷设计", () => {
  it("发起前设计问卷：弹层回填后随创建请求一起提交 schema", async () => {
    renderAt("/activity/new");

    // 切到调研
    fireEvent.click(screen.getByRole("button", { name: "调研（问卷）" }));
    expect(screen.getByText("尚未添加题目")).toBeInTheDocument();

    // 打开设计弹层并回填 1 道题
    fireEvent.click(screen.getByRole("button", { name: "设计问卷" }));
    const modal = await screen.findByRole("dialog", { name: "设计问卷" }, { timeout: 5000 });
    fireEvent.click(screen.getByRole("button", { name: "模拟完成设计" }));
    expect(modal).not.toBeInTheDocument();
    expect(screen.getByText("1 道题目")).toBeInTheDocument();
    // 设计过之后按钮文案变成「编辑问卷」
    expect(screen.getByRole("button", { name: "编辑问卷" })).toBeInTheDocument();

    // 填标题并提交
    fireEvent.change(screen.getByPlaceholderText("一句话说明"), { target: { value: "开学问卷" } });
    fireEvent.click(screen.getByRole("button", { name: "发起活动" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.type).toBe("survey");
    expect(payload.title).toBe("开学问卷");
    expect(payload.schema).toEqual(ONE_QUESTION_SCHEMA);
  });

  it("编辑已锁定的调研：设计按钮禁用并给出提示", async () => {
    getMock.mockResolvedValueOnce({
      id: 7,
      type: "survey",
      title: "已收卷的调研",
      body: "",
      start_at: null,
      end_at: "2026-11-01T10:00:00+08:00",
      is_permanent: false,
      audience: "members",
      schema: ONE_QUESTION_SCHEMA,
      schema_editable: false,
    });
    renderAt("/activity/7/edit");

    expect(await screen.findByDisplayValue("已收卷的调研")).toBeInTheDocument();
    expect(await screen.findByText("1 道题目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑问卷" })).toBeDisabled();
    expect(screen.getByText(/该问卷已收到作答，无法再修改题目/)).toBeInTheDocument();
  });
});
