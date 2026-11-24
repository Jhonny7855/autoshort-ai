import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider, useApp } from "./lib/store";
import Shell from "./components/Shell";
import Landing from "./pages/Landing";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import Automation from "./pages/Automation";
import Ideas from "./pages/Ideas";
import ScriptStudio from "./pages/ScriptStudio";
import VideoStudio from "./pages/VideoStudio";
import Queue from "./pages/Queue";
import Calendar from "./pages/Calendar";
import Publishing from "./pages/Publishing";
import Published from "./pages/Published";
import Analytics from "./pages/Analytics";
import AiEngine from "./pages/AiEngine";
import Voice from "./pages/Voice";
import SettingsPage from "./pages/Settings";
import Resources from "./pages/Resources";
import Logs from "./pages/Logs";
import { Spinner } from "./components/ui";
import "./index.css";

function Boot() {
  return (
    <div className="grid min-h-screen place-items-center">
      <div className="flex flex-col items-center gap-4">
        <div className="relative grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-600 to-cyan-500 text-base font-black text-white shadow-glow">
          AS
          <span className="absolute inset-0 overflow-hidden rounded-2xl">
            <span className="absolute inset-y-0 -left-full w-1/2 animate-sweep bg-gradient-to-r from-transparent via-white/30 to-transparent" />
          </span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <Spinner className="h-3.5 w-3.5" />
          Starting AUTOSHORT AI…
        </div>
      </div>
    </div>
  );
}

function Guard({ children }: { children: JSX.Element }) {
  const { auth, loading } = useApp();
  if (loading) return <Boot />;
  if (!auth?.authenticated) return <Navigate to="/" replace />;
  return children;
}

function Root() {
  const { auth, loading } = useApp();
  if (loading) return <Boot />;
  if (auth?.authenticated) return <Navigate to={auth.onboarding_complete ? "/dashboard" : "/onboarding"} replace />;
  return <Landing />;
}

createRoot(document.getElementById("root")!).render(
  <AppProvider>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "") || undefined}>
      <Routes>
        <Route path="/" element={<Root />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route
          element={
            <Guard>
              <Shell />
            </Guard>
          }
        >
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/automation" element={<Automation />} />
          <Route path="/ideas" element={<Ideas />} />
          <Route path="/scripts" element={<ScriptStudio />} />
          <Route path="/video" element={<VideoStudio />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/publishing" element={<Publishing />} />
          <Route path="/published" element={<Published />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/ai" element={<AiEngine />} />
          <Route path="/voice" element={<Voice />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/resources" element={<Resources />} />
          <Route path="/logs" element={<Logs />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </AppProvider>,
);
