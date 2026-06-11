import { useTranslation } from "react-i18next";
import { Server } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

export function Header() {
  const { t } = useTranslation();

  return (
    <header className="flex h-12 items-center justify-between border-b border-border/40 bg-card/70 px-4 shrink-0 backdrop-blur-lg">
      <div className="flex items-center gap-2.5">
        <Server className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold tracking-tight text-foreground/80">
          {t("common.appName")}
        </span>
      </div>
      <LanguageSwitcher />
    </header>
  );
}
