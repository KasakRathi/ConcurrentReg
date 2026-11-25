import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { ResultsProvider } from "@/hooks/results-store";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { Skeleton } from "@/components/ui/States";
import { PaletteProvider } from "@/components/nav/palette";

const Landing = lazy(() => import("@/pages/Landing"));
const DashboardLayout = lazy(() => import("@/components/dashboard/DashboardLayout"));
const Demo = lazy(() => import("@/pages/dashboard/Demo"));
const Overview = lazy(() => import("@/pages/dashboard/Overview"));
const Experiments = lazy(() => import("@/pages/dashboard/Experiments"));
const Monitoring = lazy(() => import("@/pages/dashboard/Monitoring"));
const Iasl = lazy(() => import("@/pages/dashboard/Iasl"));
const Workloads = lazy(() => import("@/pages/dashboard/Workloads"));
const Architecture = lazy(() => import("@/pages/dashboard/Architecture"));
const Results = lazy(() => import("@/pages/dashboard/Results"));
const NotFound = lazy(() => import("@/pages/NotFound"));

function ScrollToTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash) {
      const el = document.getElementById(hash.slice(1));
      if (el) {
        el.scrollIntoView();
        return;
      }
    }
    window.scrollTo(0, 0);
  }, [pathname, hash]);
  return null;
}

const Fallback = () => (
  <div className="p-8">
    <Skeleton className="h-6 w-48" />
    <Skeleton className="mt-4 h-64 w-full" />
  </div>
);

export function App() {
  return (
    <TooltipProvider>
      <ResultsProvider>
        <PaletteProvider>
        <ScrollToTop />
        <ErrorBoundary label="The page">
          <Suspense fallback={<Fallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/dashboard" element={<DashboardLayout />}>
                <Route index element={<Overview />} />
                <Route path="demo" element={<Demo />} />
                <Route path="experiments" element={<Experiments />} />
                <Route path="monitoring" element={<Monitoring />} />
                <Route path="iasl" element={<Iasl />} />
                <Route path="workloads" element={<Workloads />} />
                <Route path="architecture" element={<Architecture />} />
                <Route path="results" element={<Navigate to="/dashboard/experiments" replace />} />
                <Route path="results/:id" element={<Results />} />
              </Route>
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
        </PaletteProvider>
      </ResultsProvider>
    </TooltipProvider>
  );
}
