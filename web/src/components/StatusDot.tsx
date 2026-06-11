import { cn } from "@/lib/utils";

type Status = "online" | "offline" | "warning" | "pending" | "error";

const statusMap: Record<Status, { dot: string; ping?: string }> = {
  online: { dot: "bg-emerald-500", ping: "bg-emerald-400" },
  offline: { dot: "bg-gray-500" },
  warning: { dot: "bg-yellow-500" },
  pending: { dot: "bg-blue-500", ping: "bg-blue-400" },
  error: { dot: "bg-red-500" },
};

export function StatusDot({ status, className }: { status: Status; className?: string }) {
  const s = statusMap[status];
  return (
    <span className={cn("relative flex h-2 w-2", className)}>
      {s.ping && (
        <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", s.ping)} />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", s.dot)} />
    </span>
  );
}
