import { createRequest } from "./shared";

const request = createRequest("/tasks");

export const taskApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/tasks/${qs}`);
  },
  get: (id: number) => request(`/tasks/${id}/`),
  create: (data: object) => request("/tasks/", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: object) => request(`/tasks/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: number) => request(`/tasks/${id}/`, { method: "DELETE" }),
  myTasks: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/tasks/my_tasks/${qs}`);
  },

  // Assignment
  assign: (taskId: number, assigneeId: number | null) =>
    request(`/tasks/${taskId}/assign/`, { method: "POST", body: JSON.stringify({ assignee_id: assigneeId }) }),

  // Claim
  claim: (taskId: number, reason?: string) =>
    request(`/tasks/${taskId}/claim/`, { method: "POST", body: JSON.stringify({ reason }) }),
  approveClaim: (taskId: number, claimId: number) =>
    request(`/tasks/${taskId}/approve_claim/`, { method: "POST", body: JSON.stringify({ claim_id: claimId }) }),
  rejectClaim: (taskId: number, claimId: number) =>
    request(`/tasks/${taskId}/reject_claim/`, { method: "POST", body: JSON.stringify({ claim_id: claimId }) }),

  // Status
  complete: (taskId: number) =>
    request(`/tasks/${taskId}/complete/`, { method: "POST" }),
  cancel: (taskId: number) =>
    request(`/tasks/${taskId}/cancel/`, { method: "POST" }),
  approveCompletion: (taskId: number) =>
    request(`/tasks/${taskId}/approve_completion/`, { method: "POST" }),
  rejectCompletion: (taskId: number, reason: string) =>
    request(`/tasks/${taskId}/reject_completion/`, { method: "POST", body: JSON.stringify({ reason }) }),

  // Tags
  listTags: () => request("/tags/"),
  createTag: (data: { name: string; color?: string }) =>
    request("/tags/", { method: "POST", body: JSON.stringify(data) }),
};
