const BASE_URL = "http://localhost:8777";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? BASE_URL;

interface MCPRequest {
  jsonrpc: "2.0";
  id: number;
  method: "tools/call";
  params: {
    name: string;
    arguments: Record<string, unknown>;
  };
}

interface MCPError {
  code?: number;
  message?: string;
}

let requestId = 0;

function isToolError(text: string): boolean {
  return (
    /^Error:/i.test(text.trim()) ||
    /^Failed to execute config plan:/i.test(text.trim()) ||
    /^Authentication failed/i.test(text.trim()) ||
    /^Saved credential '.+' not found/i.test(text.trim()) ||
    /^Host '.+' 未找到/i.test(text.trim()) ||
    /^Plan '.+' (not found|has expired|is not approved|has been rejected|has already been executed)/i.test(text.trim())
  );
}

async function callTool(
  name: string,
  args: Record<string, unknown> = {}
): Promise<string> {
  const body: MCPRequest = {
    jsonrpc: "2.0",
    id: ++requestId,
    method: "tools/call",
    params: { name, arguments: args },
  };

  const res = await fetch(`${BASE_URL}/mcp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);

  const data = await res.json();
  const rpcError = data?.error as MCPError | undefined;
  if (rpcError) {
    throw new Error(rpcError.message || `JSON-RPC error${rpcError.code ? ` ${rpcError.code}` : ""}`);
  }

  const content = data?.result?.content;
  if (content && Array.isArray(content)) {
    const text = content.map((c: { type: string; text?: string }) => c.text ?? "").join("\n");
    if (isToolError(text)) throw new Error(text);
    return text;
  }
  return JSON.stringify(data);
}

function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const message = data?.detail || data?.message || `API error: ${res.status} ${res.statusText}`;
    throw new Error(message);
  }

  return data as T;
}

export const api = {
  callTool,
  parseLines,
  request,
};
