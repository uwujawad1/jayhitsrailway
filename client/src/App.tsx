import { Switch, Route, Redirect, useLocation } from "wouter";
import { useEffect, useState, lazy, Suspense } from "react";
import { apiUrl, queryClient } from "./lib/queryClient";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider, useAuth } from "@/lib/auth";
import LoginPage from "@/pages/login";
import { Loader2, ShieldCheck, Eye, EyeOff, Wrench } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

// Lazy-load every page — each is a separate JS chunk, fetched only when first visited.
// This cuts the initial bundle from ~800 kB to ~150 kB and speeds up first-paint.
const CheckerPage        = lazy(() => import("@/pages/checker"));
const CCGeneratorPage    = lazy(() => import("@/pages/cc-generator"));
const CCFilterPage       = lazy(() => import("@/pages/cc-filter"));
const GatewayFinderPage  = lazy(() => import("@/pages/gateway-finder"));
const AutoHitterPage     = lazy(() => import("@/pages/auto-hitter"));
const AutoShopifyPage    = lazy(() => import("@/pages/auto-shopify"));
const SkoolGatePage      = lazy(() => import("@/pages/skool-gate"));
const AccountCheckerPage = lazy(() => import("@/pages/account-checker"));
const ScraperPage        = lazy(() => import("@/pages/scraper"));
const UserDashboardPage  = lazy(() => import("@/pages/user-dashboard"));
const UserSettingsPage   = lazy(() => import("@/pages/user-settings"));
const PricingPage        = lazy(() => import("@/pages/pricing"));
const ReferralPage       = lazy(() => import("@/pages/referral"));
const AdminLayout        = lazy(() => import("@/components/admin-layout"));
const ActivityPopup      = lazy(() => import("@/components/activity-popup"));
const MembershipGate     = lazy(() => import("@/components/membership-gate").then(m => ({ default: m.MembershipGate })));

const VALID_PATHS = ["/", "/checker", "/user-settings", "/generator", "/filter", "/finder", "/autohitter", "/shopify", "/skool", "/accounts", "/scraper", "/pricing", "/referral", "/admin"];

function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <Loader2 className="w-6 h-6 animate-spin text-primary" />
    </div>
  );
}

function PathPersistence() {
  const [location, navigate] = useLocation();

  useEffect(() => {
    if (location !== "/") {
      sessionStorage.setItem("lastPath", location);
    }
  }, [location]);

  useEffect(() => {
    if (location === "/") {
      const saved = sessionStorage.getItem("lastPath");
      if (saved && saved !== "/" && VALID_PATHS.some(p => saved === p || saved.startsWith(p + "/"))) {
        navigate(saved, { replace: true });
      }
    }
  }, []);

  return null;
}

function AdminPinPrompt({ onVerified }: { onVerified: () => void }) {
  const [pin, setPin] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    if (!pin) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(apiUrl("/api/admin/verify-pin"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ pin }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        queryClient.invalidateQueries({ queryKey: ["/api/auth/session"] });
        onVerified();
      } else {
        setError(data.message || "Wrong PIN");
        setPin("");
      }
    } catch {
      setError("Network error. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8 border border-border rounded-xl bg-card shadow-lg">
        <div className="flex flex-col items-center gap-2">
          <div className="w-12 h-12 rounded-full bg-amber-500/10 flex items-center justify-center">
            <ShieldCheck className="w-6 h-6 text-amber-500" />
          </div>
          <h2 className="text-lg font-semibold">Admin PIN Required</h2>
          <p className="text-sm text-muted-foreground text-center">Enter your admin PIN to access the admin panel</p>
        </div>
        <div className="relative">
          <Input
            data-testid="input-admin-pin"
            type={show ? "text" : "password"}
            placeholder="Enter PIN"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="pr-10 text-center tracking-widest text-lg"
            autoFocus
          />
          <button
            type="button"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setShow(!show)}
          >
            {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
        {error && <p className="text-sm text-red-500 text-center">{error}</p>}
        <Button
          data-testid="button-verify-pin"
          className="w-full"
          onClick={submit}
          disabled={loading || !pin}
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Verify PIN"}
        </Button>
      </div>
    </div>
  );
}

function AdminGuard() {
  const { isAdmin, adminPinVerified, refetchSession } = useAuth();

  if (!isAdmin) {
    return <Redirect to="/" />;
  }

  if (!adminPinVerified) {
    return <AdminPinPrompt onVerified={refetchSession} />;
  }

  return (
    <Suspense fallback={<PageLoader />}>
      <AdminLayout />
    </Suspense>
  );
}

function MaintenanceOverlay() {
  const { isAdmin } = useAuth();
  const { data } = useQuery<{ maintenance: boolean }>({
    queryKey: ["/api/maintenance"],
    refetchInterval: 30000,
  });

  if (!data?.maintenance || isAdmin) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-background/95 backdrop-blur-sm">
      <div className="w-full max-w-sm mx-4 text-center space-y-6 p-8 border border-border rounded-2xl bg-card shadow-2xl">
        <div className="flex flex-col items-center gap-3">
          <div className="w-16 h-16 rounded-full bg-orange-500/10 flex items-center justify-center">
            <Wrench className="w-8 h-8 text-orange-500" />
          </div>
          <h2 className="text-xl font-bold">Under Maintenance</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            We're currently performing maintenance on the app.<br />
            Please come back later.
          </p>
        </div>
        <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <div className="w-2 h-2 rounded-full bg-orange-500 animate-pulse" />
          <span>Maintenance in progress</span>
        </div>
      </div>
    </div>
  );
}

function AppRoutes() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <PageLoader />;
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <Suspense fallback={<PageLoader />}>
      <PathPersistence />
      <Switch>
        <Route path="/" component={UserDashboardPage} />
        <Route path="/checker" component={CheckerPage} />
        <Route path="/user-settings" component={UserSettingsPage} />
        <Route path="/generator" component={CCGeneratorPage} />
        <Route path="/filter" component={CCFilterPage} />
        <Route path="/finder" component={GatewayFinderPage} />
        <Route path="/autohitter" component={AutoHitterPage} />
        <Route path="/shopify" component={AutoShopifyPage} />
        <Route path="/skool" component={SkoolGatePage} />
        <Route path="/accounts" component={AccountCheckerPage} />
        <Route path="/scraper" component={ScraperPage} />
        <Route path="/pricing" component={PricingPage} />
        <Route path="/referral" component={ReferralPage} />
        <Route path="/admin/:rest*" component={AdminGuard} />
        <Route path="/admin" component={AdminGuard} />
        <Route><Redirect to="/" /></Route>
      </Switch>
    </Suspense>
  );
}

function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <AuthProvider>
            <Suspense fallback={null}>
              <MembershipGate>
                <AppRoutes />
                <ActivityPopup />
                <MaintenanceOverlay />
              </MembershipGate>
            </Suspense>
          </AuthProvider>
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
