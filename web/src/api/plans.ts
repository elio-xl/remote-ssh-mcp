import { api } from "./client";

interface PlansResponse {
  success: boolean;
  plans: unknown[];
}

export const plansApi = {
  list() {
    return api.request<PlansResponse>("/api/remote/plans");
  },

  get(planId: string) {
    return api.request<{ success: boolean; plan: unknown }>(`/api/remote/plans/${encodeURIComponent(planId)}`);
  },

  approve(planId: string, note?: string) {
    return api.request(`/api/remote/plans/${encodeURIComponent(planId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ comment: note }),
    });
  },

  reject(planId: string, reason?: string) {
    return api.request(`/api/remote/plans/${encodeURIComponent(planId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  execute(planId: string) {
    return api.request(`/api/remote/plans/${encodeURIComponent(planId)}/execute`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },
};
