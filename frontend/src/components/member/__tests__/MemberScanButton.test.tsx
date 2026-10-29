import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { checkMock, lookupMock, startMock, stopMock, imageMock } = vi.hoisted(() => ({
  checkMock: vi.fn(),
  lookupMock: vi.fn(),
  startMock: vi.fn(),
  stopMock: vi.fn(),
  imageMock: vi.fn(),
}));

vi.mock("../../../api/client", () => ({
  api: { memberCheck: checkMock, memberLookup: lookupMock },
}));

vi.mock("../barcodeScanner", () => ({
  startCameraScan: startMock,
  scanImageFile: imageMock,
}));

import MemberScanButton from "../MemberScanButton";

const SIG = "0123456789abcdef";
const CARD = { name: "张三", cohort: 1, code: "26010201", status: "active", avatar: null };

/** 让组件"扫描"到一段文本：调用 startCameraScan 时抓到的回调。 */
let emit: ((text: string) => void) | null = null;

async function openScanner() {
  render(<MemberScanButton />);
  fireEvent.click(screen.getByRole("button", { name: /扫描条码/ }));
  await waitFor(() => expect(startMock).toHaveBeenCalled());
}

async function scan(text: string) {
  await act(async () => {
    emit?.(text);
  });
}

describe("MemberScanButton（首页扫描条码）", () => {
  beforeEach(() => {
    emit = null;
    checkMock.mockReset();
    lookupMock.mockReset();
    startMock.mockReset();
    stopMock.mockReset();
    imageMock.mockReset();
    startMock.mockImplementation(async (_video: HTMLVideoElement, onText: (t: string) => void) => {
      emit = onText;
      return { stop: stopMock };
    });
  });

  it("点按钮打开取景弹窗并启动摄像头", async () => {
    await openScanner();
    expect(screen.getByRole("dialog", { name: "扫描工牌条码" })).toBeInTheDocument();
    expect(screen.getByText(/对准工牌上的二维码或条形码/)).toBeInTheDocument();
    expect(startMock).toHaveBeenCalledTimes(1);
  });

  it("扫到工牌二维码 → 走校验接口并弹出结果卡（不扣额度）", async () => {
    checkMock.mockResolvedValue({ found: true, ...CARD });
    await openScanner();

    await scan(`https://8.153.145.175/#/v/26010201?s=${SIG}`);

    expect(checkMock).toHaveBeenCalledWith("26010201", SIG);
    expect(await screen.findByText("张三")).toBeInTheDocument();
    expect(screen.getByText("识别码 26010201")).toBeInTheDocument();
    expect(screen.getByText("本页来自工牌二维码扫码，仅展示公开信息。")).toBeInTheDocument();
    expect(lookupMock).not.toHaveBeenCalled();
    expect(stopMock).toHaveBeenCalled(); // 命中后立刻关摄像头
  });

  it("扫到条形码 → 走查询接口，并把最新额度回传给外层", async () => {
    const quota = { limit: 3, used: 1, remaining: 2, reset_at: null, window_hours: 24 };
    lookupMock.mockResolvedValue({ found: true, results: [CARD], quota });
    const onQuotaChange = vi.fn();

    render(<MemberScanButton onQuotaChange={onQuotaChange} />);
    fireEvent.click(screen.getByRole("button", { name: /扫描条码/ }));
    await waitFor(() => expect(startMock).toHaveBeenCalled());

    await scan("26010201");

    expect(lookupMock).toHaveBeenCalledWith("26010201");
    expect(await screen.findByText("张三")).toBeInTheDocument();
    expect(screen.getByText("本页来自工牌条形码查询，仅展示公开信息。")).toBeInTheDocument();
    expect(onQuotaChange).toHaveBeenCalledWith(quota);
  });

  it("工牌无效（校验接口 404）→ 提示未找到", async () => {
    checkMock.mockRejectedValue(Object.assign(new Error("Not found"), { status: 404 }));
    await openScanner();

    await scan(`https://8.153.145.175/#/v/26010201?s=${SIG}`);

    expect(await screen.findByText(/无效、已失效或不属于本站/)).toBeInTheDocument();
  });

  it("扫到非本站内容 → 明确提示识别不了", async () => {
    await openScanner();

    await scan("https://example.com/hello");

    expect(await screen.findByRole("alert")).toHaveTextContent("不是本站工牌");
    expect(checkMock).not.toHaveBeenCalled();
  });

  it("摄像头被拒绝 → 给出人话提示并保留选图兜底", async () => {
    startMock.mockRejectedValue(Object.assign(new Error("Permission denied"), { name: "NotAllowedError" }));
    render(<MemberScanButton />);
    fireEvent.click(screen.getByRole("button", { name: /扫描条码/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("摄像头权限被拒绝");
    expect(screen.getByText("拍照 / 选图识别")).toBeInTheDocument();
  });

  it("关闭弹窗会停掉摄像头", async () => {
    await openScanner();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(stopMock).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
