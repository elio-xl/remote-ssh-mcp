import { api } from "./client";
import type { EventFilter } from "@/lib/types";

interface AuditResponse {
  success: boolean;
  events: unknown[];
}

export const logsApi = {
  read(limit = 50, eventFilter?: EventFilter) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (eventFilter) params.set("event_type", eventFilter);
    return api.request<AuditResponse>(`/api/remote/audit-events?${params.toString()}`);
  },
};
