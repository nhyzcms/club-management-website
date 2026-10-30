import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { Event, EventFormData } from "../types/events";

const request = createRequest("/events");

export const eventApi = {
  list: (params?: Record<string, string>): Promise<Paginated<Event>> => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/${qs}`);
  },
  get: (id: number): Promise<Event> => request(`/${id}/`),
  create: (data: EventFormData): Promise<Event> =>
    request("/", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: Partial<EventFormData>): Promise<Event> =>
    request(`/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
  remove: (id: number) => request(`/${id}/`, { method: "DELETE" }),
  publish: (id: number): Promise<Event> =>
    request(`/${id}/publish/`, { method: "POST" }),
  archive: (id: number): Promise<Event> =>
    request(`/${id}/archive/`, { method: "POST" }),
};
