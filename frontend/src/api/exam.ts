import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";

const request = createRequest("/exam_board");

export interface ExamSubject {
  id: number;
  name: string;
  exam_date: string;
  start_time: string;
  end_time: string;
  sort_order: number;
}

export interface ExamBatch {
  id: number;
  name: string;
  sort_order: number;
  subjects: ExamSubject[];
}

export interface Exam {
  id: number;
  title: string;
  batches: ExamBatch[];
  created_at: string;
  updated_at: string;
}

export interface ExamListItem {
  id: number;
  title: string;
  batch_count: number;
  created_at: string;
  updated_at: string;
}

export interface ExamClock {
  timestamp: number;
  timezone: string;
  iso: string;
}

export interface ExamErrata {
  id: number;
  exam: number;
  text: string;
  image_url: string | null;
  created_at: string;
  expires_at: string | null;
}

export type ExamWritePayload = {
  title: string;
  batches: {
    name: string;
    sort_order?: number;
    subjects: {
      name: string;
      exam_date: string;
      start_time: string;
      end_time: string;
      sort_order?: number;
    }[];
  }[];
};

export const examApi = {
  list: () => request("/exams/") as Promise<Paginated<ExamListItem>>,
  latest: () => request("/exams/latest/") as Promise<{ status: string; data: Exam | null; message?: string }>,
  retrieve: (id: number) => request(`/exams/${id}/`) as Promise<Exam>,
  create: (data: ExamWritePayload) =>
    request("/exams/", { method: "POST", body: JSON.stringify(data) }) as Promise<Exam>,
  update: (id: number, data: ExamWritePayload) =>
    request(`/exams/${id}/`, { method: "PUT", body: JSON.stringify(data) }) as Promise<Exam>,
  remove: (id: number) => request(`/exams/${id}/`, { method: "DELETE" }) as Promise<void>,
  clock: () => request("/exams/clock/") as Promise<ExamClock>,
  currentErrata: (examId?: number | null) => {
    const q = examId != null ? `?exam=${examId}` : "";
    return request(`/errata/current/${q}`) as Promise<{ status: string; data: ExamErrata[] }>;
  },
  publishErrata: (data: FormData) =>
    request("/errata/", { method: "POST", body: data }) as Promise<ExamErrata>,
  dismissErrata: (examId?: number | null) => {
    const body = examId != null ? JSON.stringify({ exam: examId }) : "{}";
    return request("/errata/dismiss/", { method: "POST", body }) as Promise<{
      status: string;
      dismissed: number;
      ids: number[];
    }>;
  },
};
