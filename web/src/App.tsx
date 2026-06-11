import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "sonner";
import { Layout } from "@/components/Layout";
import { PlanProvider } from "@/contexts/PlanContext";
import { ConfigEditorPage } from "@/pages/ConfigEditor";
import { ConfigDetailPage } from "@/pages/ConfigDetail";
import { PlansPage } from "@/pages/Plans";
import { LogsPage } from "@/pages/Logs";
import "@/i18n";

export default function App() {
  return (
    <HashRouter>
      <TooltipProvider>
        <PlanProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/config" element={<ConfigEditorPage />} />
              <Route path="/config/:host" element={<ConfigDetailPage />} />
              <Route path="/plans" element={<PlansPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="*" element={<Navigate to="/config" replace />} />
            </Route>
          </Routes>
        </PlanProvider>
        <Toaster theme="system" />
      </TooltipProvider>
    </HashRouter>
  );
}
