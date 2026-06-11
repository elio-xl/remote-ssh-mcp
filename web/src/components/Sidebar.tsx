import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Server, Shield, ScrollText } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatusDot } from "@/components/StatusDot";
import { cn } from "@/lib/utils";
import { usePlans } from "@/contexts/PlanContext";

export function Sidebar() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const { plans } = usePlans();

  const pendingCount = plans.filter(
    (p) => p.status === "pending_approval" || p.status === "draft"
  ).length;

  const navItems = [
    { to: "/config", icon: Server, label: t("nav.config") },
    { to: "/plans", icon: Shield, label: t("nav.plans"), badge: pendingCount },
    { to: "/logs", icon: ScrollText, label: t("nav.logs") },
  ];

  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-border/40 bg-sidebar/70 backdrop-blur-lg">
      <ScrollArea className="flex-1">
        <nav className="flex flex-col gap-0.5 p-2">
          {navItems.map(({ to, icon: Icon, label, badge }) => {
            const active = pathname === to || pathname.startsWith(to + "/") || pathname.startsWith(to + "?");
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-foreground/70 hover:bg-black/5 dark:hover:bg-white/5"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="flex-1 truncate">{label}</span>
                {badge != null && badge > 0 && (
                  <span
                    className={cn(
                      "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
                      active
                        ? "bg-primary text-primary-foreground"
                        : "bg-black/10 text-foreground/60 dark:bg-white/10"
                    )}
                  >
                    {badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </ScrollArea>
      <div className="border-t border-border/40 p-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <StatusDot status="online" />
          <span className="truncate">ssh-mcp-server</span>
        </div>
      </div>
    </aside>
  );
}
