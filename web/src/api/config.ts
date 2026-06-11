import { invoke } from "@tauri-apps/api/core";
import { api } from "./client";
import type { SSHConfigCrudEntry } from "@/lib/types";

interface APIResponse {
  success: boolean;
  message: string;
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export const configApi = {
  path() {
    if (isTauriRuntime()) {
      return invoke<string>("get_ssh_config_path");
    }
    return Promise.resolve("仓库根目录 ssh_config（Python 后端开发模式）");
  },

  list() {
    if (isTauriRuntime()) {
      return invoke<SSHConfigCrudEntry[]>("list_ssh_configs");
    }
    return api.request<SSHConfigCrudEntry[]>("/api/ssh-configs");
  },

  get(host: string) {
    if (isTauriRuntime()) {
      return invoke<SSHConfigCrudEntry | null>("get_ssh_config", { host }).then((entry) => {
        if (!entry) throw new Error(`Host '${host}' 未找到`);
        return entry;
      });
    }
    return api.request<SSHConfigCrudEntry>(`/api/ssh-configs/${encodeURIComponent(host)}`);
  },

  create(payload: SSHConfigCrudEntry) {
    if (isTauriRuntime()) {
      return invoke<SSHConfigCrudEntry>("create_ssh_config", { payload });
    }
    return api.request<SSHConfigCrudEntry>("/api/ssh-configs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  update(host: string, payload: SSHConfigCrudEntry) {
    if (isTauriRuntime()) {
      return invoke<SSHConfigCrudEntry>("update_ssh_config", { host, payload });
    }
    return api.request<SSHConfigCrudEntry>(`/api/ssh-configs/${encodeURIComponent(host)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  rename(host: string, newHost: string) {
    return api.request<SSHConfigCrudEntry>(`/api/ssh-configs/${encodeURIComponent(host)}/rename`, {
      method: "POST",
      body: JSON.stringify({ newHost }),
    });
  },

  delete(host: string) {
    if (isTauriRuntime()) {
      return invoke<boolean>("delete_ssh_config", { host }).then((success) => ({
        success,
        message: success ? "删除成功" : "删除失败",
      }));
    }
    return api.request<APIResponse>(`/api/ssh-configs/${encodeURIComponent(host)}`, {
      method: "DELETE",
    });
  },

  test(payload: SSHConfigCrudEntry) {
    if (isTauriRuntime()) {
      return invoke<APIResponse>("test_ssh_connection", { payload });
    }
    return api.request<APIResponse>("/api/ssh-configs/test", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
