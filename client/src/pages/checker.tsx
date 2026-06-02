import { useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetTrigger, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  CreditCard, Zap, Shield, ShieldAlert, ShieldX, ShieldCheck,
  Loader2, Trash2, Copy, CheckCircle2, XCircle, AlertCircle, Clock,
  Menu, ShieldEllipsis, LogOut, User, Sparkles, Search, Target, Filter,
  ShoppingCart, GraduationCap, LayoutDashboard, Settings, Tv, Gamepad2, BookOpen,
  ExternalLink, ShieldOff
} from "lucide-react";
import { PageTransition } from "@/components/page-transition";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/lib/auth";
import { apiRequest, apiUrl } from "@/lib/queryClient";

interface Gateway {
  id: string;
  name: string;
  type: string;
  category: string;
  enabled: boolean;
  premiumOnly: boolean;
}

interface CheckResult {
  id: string;
  status: string;
  response: string;
  gateway?: string;
  card?: string;
  timestamp?: number;
}

interface LogEntry {
  time: string;
  message: string;
  type: "info" | "success" | "error" | "warn";
}

function getStatusIcon(status: string) {
  switch (status) {
    case "charged": return <ShieldCheck className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "approved": return <CheckCircle2 className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "declined": return <XCircle className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "unknown": return <AlertCircle className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "checking": return <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 animate-spin" />;
    default: return <ShieldX className="w-4 h-4 lg:w-5 lg:h-5" />;
  }
}

function getStatusEmoji(status: string) {
  switch (status) {
    case "charged": return "💳";
    case "approved": return "✅";
    case "declined": return "❌";
    case "unknown": return "⚠️";
    case "checking": return "🔄";
    default: return "🚫";
  }
}

function getStatusLabel(status: string) {
  switch (status) {
    case "charged": return "CHARGED 💰";
    case "approved": return "APPROVED ✅";
    case "declined": return "DECLINED ❌";
    case "unknown": return "UNKNOWN ⚠️";
    case "checking": return "CHECKING...";
    default: return "ERROR 🚫";
  }
}

function getStatusColor(status: string) {
  switch (status) {
    case "charged": return "text-emerald-400";
    case "approved": return "text-blue-400";
    case "declined": return "text-red-400";
    case "unknown": return "text-yellow-400";
    case "checking": return "text-muted-foreground";
    default: return "text-red-400";
  }
}

function getStatusBg(status: string) {
  switch (status) {
    case "charged": return "bg-emerald-500/10 border-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.15)]";
    case "approved": return "bg-blue-500/10 border-blue-500/30 shadow-[0_0_12px_rgba(59,130,246,0.15)]";
    case "declined": return "bg-red-500/10 border-red-500/20";
    case "unknown": return "bg-yellow-500/10 border-yellow-500/20";
    case "checking": return "bg-muted/50 border-border";
    default: return "bg-red-500/10 border-red-500/20";
  }
}

function extractChargeAmount(response: string): string | null {
  const match = response.match(/\$[\d,.]+|\€[\d,.]+|£[\d,.]+|₹[\d,.]+|\d+\.\d{2}\s*(USD|EUR|GBP|INR)/i);
  return match ? match[0] : null;
}

function getLogColor(type: string) {
  switch (type) {
    case "success": return "text-emerald-400";
    case "error": return "text-red-400";
    case "warn": return "text-yellow-400";
    default: return "text-muted-foreground";
  }
}

interface JobDetail {
  jobId: string;
  status: "running" | "completed" | "stopped";
  gateway: string;
  totalCards: number;
  processedCards: number;
  results: { id: string; card: string; status: string; response: string; timestamp: number }[];
  allResultsCount: number;
  createdAt: number;
  completedAt?: number;
}

export default function CheckerPage() {
  const [selectedGateway, setSelectedGateway] = useState<string>("");
  const [cardInput, setCardInput] = useState<string>("");
  const [results, setResults] = useState<CheckResult[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [checking, setChecking] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [totalCards, setTotalCards] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showSkoolPopup, setShowSkoolPopup] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const safetyTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pollErrorCountRef = useRef<number>(0);
  const seenCountRef = useRef<number>(0);
  const { toast } = useToast();
  const { user, isAdmin, logout } = useAuth();
  const [, navigate] = useLocation();

  const { data: checkerStatuses } = useQuery<Record<string, boolean>>({
    queryKey: ["/api/account-checkers/status"],
  });

  const { data: gateways = [], isLoading: gatewaysLoading, isError: gatewaysError } = useQuery<Gateway[]>({
    queryKey: ["/api/checker/gateways"],
    refetchInterval: 10000,
  });

  const { data: existingJobs } = useQuery<any[]>({
    queryKey: ["/api/check/batch"],
    staleTime: 0,
    refetchInterval: activeJobId ? false : 5000,
  });

  const resumedRef = useRef(false);

  useEffect(() => {
    if (resumedRef.current || !existingJobs || activeJobId) return;

    const runningJob = existingJobs.find((j: any) => j.status === "running");
    const targetJob = runningJob || existingJobs.find((j: any) => {
      if (j.status !== "completed") return false;
      const recencyTs = j.completedAt ?? j.createdAt;
      return recencyTs > Date.now() - 30 * 60 * 1000;
    });

    if (targetJob) {
      resumedRef.current = true;
      setActiveJobId(targetJob.jobId);
      setChecking(targetJob.status === "running");
      setTotalCards(targetJob.totalCards);
      setCurrentIndex(targetJob.processedCards);
      seenCountRef.current = 0;
      const gw = gateways.find(g => g.id === targetJob.gateway);
      if (gw && !selectedGateway) setSelectedGateway(gw.id);
    }
  }, [existingJobs, activeJobId, gateways, selectedGateway]);

  useEffect(() => {
    if (!activeJobId) return;

    const poll = async () => {
      try {
        const res = await fetch(apiUrl(`/api/check/batch/${activeJobId}?after=${seenCountRef.current}`), {
          credentials: "include",
        });
        if (!res.ok) {
          if (res.status === 404 || res.status === 403) {
            setActiveJobId(null);
            setChecking(false);
            resumedRef.current = false;
            seenCountRef.current = 0;
            if (pollRef.current) clearInterval(pollRef.current);
          }
          return;
        }
        const data: JobDetail = await res.json();
        setCurrentIndex(data.processedCards);
        setTotalCards(data.totalCards);

        if (data.results.length > 0) {
          const gateName = gateways.find(g => g.id === data.gateway)?.name || data.gateway;
          const newResults: CheckResult[] = data.results.map(r => ({
            id: r.id,
            status: r.status,
            response: r.response,
            card: r.card,
            gateway: gateName,
            timestamp: r.timestamp,
          }));

          seenCountRef.current = data.allResultsCount;

          for (const r of newResults) {
            const logType = r.status === "charged" ? "success" as const :
              r.status === "approved" ? "success" as const :
              r.status === "declined" ? "error" as const : "warn" as const;
            const time = new Date(r.timestamp).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
            setLogs(p => [...p, { time, message: `${r.card} → ${r.status.toUpperCase()}: ${(r.response || "").slice(0, 80)}`, type: logType }]);
          }

          setResults(prev => [...newResults, ...prev]);
        }

        if (data.status !== "running") {
          if (pollRef.current) clearInterval(pollRef.current);
          if (safetyTimeoutRef.current) clearTimeout(safetyTimeoutRef.current);
          pollErrorCountRef.current = 0;
          setChecking(false);
          addLog("Check complete", "info");
        } else {
          pollErrorCountRef.current = 0;
        }
      } catch {
        pollErrorCountRef.current += 1;
        if (pollErrorCountRef.current >= 5) {
          if (pollRef.current) clearInterval(pollRef.current);
          if (safetyTimeoutRef.current) clearTimeout(safetyTimeoutRef.current);
          pollErrorCountRef.current = 0;
          setChecking(false);
          addLog("Connection lost — checker stopped", "error");
          toast({ title: "Connection lost", description: "Could not reach server after 5 retries. Check may still run in background.", variant: "destructive" });
        }
      }
    };

    pollErrorCountRef.current = 0;
    poll();
    pollRef.current = setInterval(poll, 3000);

    // Safety valve: if still loading after 5 minutes, stop the spinner
    safetyTimeoutRef.current = setTimeout(() => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollErrorCountRef.current = 0;
      setChecking(false);
      addLog("Check timed out — may still run in background", "warn");
      toast({ title: "Checker timed out", description: "The UI check timed out. The job may still be running in the background.", variant: "destructive" });
    }, 5 * 60 * 1000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (safetyTimeoutRef.current) clearTimeout(safetyTimeoutRef.current);
    };
  }, [activeJobId, gateways]);

  const authGates = gateways.filter(g => g.category === "auth");
  const chargeGates = gateways.filter(g => g.category === "charge");
  const enabledAuthGates = authGates.filter(g => g.enabled);
  const disabledAuthGates = authGates.filter(g => !g.enabled);
  const enabledChargeGates = chargeGates.filter(g => g.enabled);
  const disabledChargeGates = chargeGates.filter(g => !g.enabled);

  const addLog = (message: string, type: LogEntry["type"] = "info") => {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setLogs(prev => [...prev, { time, message, type }]);
  };

  const handleCheck = async () => {
    if (!selectedGateway) {
      toast({ title: "Select a gateway", variant: "destructive" });
      return;
    }
    const cards = cardInput
      .split("\n")
      .map(c => c.trim())
      .filter(c => c && /^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(c));

    if (cards.length === 0) {
      toast({ title: "Enter valid cards", description: "Format: CC|MM|YY|CVV", variant: "destructive" });
      return;
    }

    setStarting(true);
    setLogs([]);
    const gateName = gateways.find(g => g.id === selectedGateway)?.name || selectedGateway;
    addLog(`Starting check: ${cards.length} card(s) via ${gateName}`, "info");

    try {
      const res = await apiRequest("POST", "/api/check/batch", { gateway: selectedGateway, cards });
      const data = await res.json();
      resumedRef.current = true;
      setActiveJobId(data.jobId);
      setResults([]);
      seenCountRef.current = 0;
      setChecking(true);
      setTotalCards(data.totalCards);
      setCurrentIndex(0);
      setCardInput("");
      toast({ title: `Checking ${data.totalCards} cards`, description: "Runs in background — you can leave this page" });
    } catch (err: any) {
      let msg = "Failed to start";
      try {
        const raw = err.message || "";
        const jsonStr = raw.replace(/^\d+:\s*/, "");
        const p = JSON.parse(jsonStr);
        msg = p.error || p.message || msg;
      } catch {
        if (err.message && !err.message.startsWith("Failed")) msg = err.message;
      }
      toast({ title: msg, variant: "destructive" });
      addLog(`Failed: ${msg}`, "error");
    }
    setStarting(false);
  };

  const handleStop = async () => {
    if (!activeJobId) return;
    setStopping(true);
    try {
      await apiRequest("DELETE", `/api/check/batch/${activeJobId}`);
      toast({ title: "Stopping check..." });
      addLog("Stopping check...", "warn");
    } catch {
      toast({ title: "Failed to stop", variant: "destructive" });
    }
    setStopping(false);
  };

  const clearResults = () => {
    setResults([]);
    setLogs([]);
    setActiveJobId(null);
    seenCountRef.current = 0;
    resumedRef.current = false;
  };

  const copyResults = () => {
    const gatewayInfo = gateways.find(g => g.id === selectedGateway);
    const gatewayName = gatewayInfo?.name || selectedGateway;
    const text = results
      .filter(r => r.status !== "checking")
      .map(r => {
        const emoji = r.status === "charged" ? "💳" : r.status === "approved" ? "✅" : r.status === "declined" ? "❌" : "⚠️";
        const amount = r.response ? extractChargeAmount(r.response) : null;
        return `${emoji} ${r.card} | ${r.status.toUpperCase()} | ${gatewayName}${amount ? ` | ${amount}` : ""} | ${r.response}`;
      })
      .join("\n");
    navigator.clipboard.writeText(text);
    toast({ title: "Copied to clipboard" });
  };

  const charged = results.filter(r => r.status === "charged").length;
  const approved = results.filter(r => r.status === "approved").length;
  const declined = results.filter(r => r.status === "declined").length;
  const errors = results.filter(r => r.status === "error" || r.status === "unknown").length;

  return (
    <div className="app-shell flex flex-col min-h-screen">
      <header className="app-topbar">
        <div className="flex items-center gap-3">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" data-testid="button-hamburger">
                <Menu className="w-5 h-5 lg:w-6 lg:h-6" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0 flex flex-col">
              <SheetHeader className="p-4 border-b shrink-0">
                <SheetTitle className="flex items-center gap-2">
                  <CreditCard className="w-5 h-5 text-primary" />
                  JayHits
                </SheetTitle>
                <SheetDescription className="sr-only">Navigation menu and tools</SheetDescription>
              </SheetHeader>
              <div className="flex flex-col p-4 gap-2 flex-1 overflow-y-auto">
                <div className="flex items-center gap-2 p-3 rounded-md bg-muted/50">
                  <User className="w-4 h-4 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium" data-testid="text-user-name">
                      {[user?.firstName, user?.lastName].filter(Boolean).join(" ") || user?.username || `ID: ${user?.userId}`}
                    </p>
                    <p className="text-xs text-muted-foreground" data-testid="text-user-role">
                      {isAdmin ? "Admin" : "User"} · {user?.userId}
                    </p>
                  </div>
                </div>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/"); }}
                  data-testid="button-dashboard"
                >
                  <LayoutDashboard className="w-4 h-4" />
                  Dashboard
                </Button>

                <div className="text-xs text-muted-foreground font-semibold mt-2 mb-1 px-1">Tools</div>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2 bg-primary/10"
                  onClick={() => { setMenuOpen(false); navigate("/checker"); }}
                  data-testid="button-checker"
                >
                  <Zap className="w-4 h-4" />
                  C-C Checker
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/generator"); }}
                  data-testid="button-cc-generator"
                >
                  <Sparkles className="w-4 h-4" />
                  CC Generator
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/finder"); }}
                  data-testid="button-gateway-finder"
                >
                  <Search className="w-4 h-4" />
                  Gateway Finder
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/autohitter"); }}
                  data-testid="button-auto-hitter"
                >
                  <Target className="w-4 h-4" />
                  Auto Hitter
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/filter"); }}
                  data-testid="button-cc-filter"
                >
                  <Filter className="w-4 h-4" />
                  CC Filter
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/shopify"); }}
                  data-testid="button-auto-shopify"
                >
                  <ShoppingCart className="w-4 h-4" />
                  Auto Shopify
                </Button>

                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2"
                  onClick={() => { setMenuOpen(false); navigate("/skool"); }}
                  data-testid="button-skool-gate"
                >
                  <GraduationCap className="w-4 h-4" />
                  Skool Gate
                </Button>

                {[
                  { id: "crunchyroll", label: "Crunchyroll Checker", icon: Tv, testId: "button-crunchyroll-checker" },
                  { id: "xbox", label: "Xbox Checker", icon: Gamepad2, testId: "button-xbox-checker" },
                  { id: "cyberghost", label: "CyberGhost Checker", icon: Shield, testId: "button-cyberghost-checker" },
                  { id: "duolingo", label: "Duolingo Checker", icon: BookOpen, testId: "button-duolingo-checker" },
                  { id: "hoichoi", label: "Hoichoi Checker", icon: Tv, testId: "button-hoichoi-checker" },
                ].filter(c => !checkerStatuses || checkerStatuses[c.id] !== false).length > 0 && (
                  <div className="text-xs text-muted-foreground font-semibold mt-2 mb-1 px-1">Account Checkers</div>
                )}

                {[
                  { id: "crunchyroll", label: "Crunchyroll Checker", icon: Tv, testId: "button-crunchyroll-checker" },
                  { id: "xbox", label: "Xbox Checker", icon: Gamepad2, testId: "button-xbox-checker" },
                  { id: "cyberghost", label: "CyberGhost Checker", icon: Shield, testId: "button-cyberghost-checker" },
                  { id: "duolingo", label: "Duolingo Checker", icon: BookOpen, testId: "button-duolingo-checker" },
                  { id: "hoichoi", label: "Hoichoi Checker", icon: Tv, testId: "button-hoichoi-checker" },
                ].filter(c => !checkerStatuses || checkerStatuses[c.id] !== false).map(checker => (
                  <Button key={checker.id} variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate(`/accounts?checker=${checker.id}`); }} data-testid={checker.testId}>
                    <checker.icon className="w-4 h-4" />
                    {checker.label}
                  </Button>
                ))}

                <div className="border-t mt-2 pt-2">
                  <Button
                    variant="ghost"
                    className="w-full justify-start gap-2"
                    onClick={() => { setMenuOpen(false); navigate("/user-settings"); }}
                    data-testid="button-settings"
                  >
                    <Settings className="w-4 h-4" />
                    Settings
                  </Button>

                  {isAdmin && (
                    <Button
                      variant="outline"
                      className="w-full justify-start gap-2 mb-2"
                      onClick={() => { setMenuOpen(false); navigate("/admin"); }}
                      data-testid="button-admin-panel"
                    >
                      <ShieldEllipsis className="w-4 h-4" />
                      Admin Panel
                    </Button>
                  )}

                  <Button
                    variant="ghost"
                    className="w-full justify-start gap-2 text-destructive hover:text-destructive"
                    onClick={() => { setMenuOpen(false); logout(); }}
                    data-testid="button-logout"
                  >
                    <LogOut className="w-4 h-4" />
                    Logout
                  </Button>
                </div>
              </div>
            </SheetContent>
          </Sheet>
          <div className="app-topbar__title">
            <div className="app-topbar__icon">
              <CreditCard className="w-5 h-5 lg:w-6 lg:h-6 text-primary" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary/80">Verification Lab</p>
              <h1 className="text-lg font-semibold lg:text-xl" data-testid="text-page-title">Checker</h1>
            </div>
          </div>
          {checking && (
            <Badge variant="secondary" className="text-xs" data-testid="badge-progress">
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
              {currentIndex}/{totalCards}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate("/admin")}
              data-testid="button-admin-header"
              title="Admin Panel"
            >
              <ShieldEllipsis className="w-4 h-4" />
            </Button>
          )}
          <div className="app-chip">Batch Engine</div>
        </div>
      </header>

      <PageTransition className="app-page flex-1 overflow-x-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 lg:gap-6">
          <div className="lg:col-span-2 flex flex-col gap-4 lg:gap-6">
            <Card>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <span className="lg:text-xl">⚡</span>
                  Gateway
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                {gatewaysLoading && (
                  <div className="flex items-center gap-2 text-xs lg:text-sm text-muted-foreground py-2">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Loading gateways...
                  </div>
                )}
                {gatewaysError && (
                  <div className="text-xs lg:text-sm text-red-400 py-2">Failed to load gateways</div>
                )}
                <Select
                  value={selectedGateway}
                  onValueChange={setSelectedGateway}
                  disabled={checking || gatewaysLoading || gatewaysError}
                >
                  <SelectTrigger data-testid="select-gateway">
                    <SelectValue placeholder="Select gateway..." />
                  </SelectTrigger>
                  <SelectContent>
                    {authGates.length > 0 && (
                      <>
                        <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">Auth Gates</div>
                        {authGates.map(g => (
                          <SelectItem key={g.id} value={g.id} data-testid={`option-gateway-${g.id}`}>
                            <div className="flex items-center gap-2">
                              <Shield className="w-3 h-3 text-blue-400" />
                              <span>{g.name}</span>
                              {g.premiumOnly && <Badge variant="secondary" className="text-[10px] px-1 py-0">PRO</Badge>}
                            </div>
                          </SelectItem>
                        ))}
                      </>
                    )}
                    {chargeGates.length > 0 && (
                      <>
                        <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">Charge Gates</div>
                        {chargeGates.map(g => (
                          <SelectItem key={g.id} value={g.id} data-testid={`option-gateway-${g.id}`}>
                            <div className="flex items-center gap-2">
                              <ShieldAlert className="w-3 h-3 text-yellow-400" />
                              <span>{g.name}</span>
                              {g.premiumOnly && <Badge variant="secondary" className="text-[10px] px-1 py-0">PRO</Badge>}
                            </div>
                          </SelectItem>
                        ))}
                      </>
                    )}
                  </SelectContent>
                </Select>
              </CardContent>
            </Card>

            <Card className="flex-1 flex flex-col min-h-0 animate-fade-in-up" style={{ animationDelay: "100ms" }}>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <span className="lg:text-xl">💳</span>
                  Cards
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex-1 flex flex-col gap-3 min-h-0">
                <Textarea
                  placeholder={"4111111111111111|12|25|123\n5500000000000004|06|26|456\n..."}
                  value={cardInput}
                  onChange={e => setCardInput(e.target.value)}
                  disabled={checking}
                  className="flex-1 min-h-[120px] max-h-[200px] lg:min-h-[160px] lg:max-h-[280px] font-mono text-xs lg:text-sm resize-none"
                  data-testid="input-cards"
                />
                <div className="flex gap-2">
                  {!checking ? (
                    <Button
                      onClick={handleCheck}
                      disabled={!selectedGateway || !cardInput.trim() || gatewaysLoading || gatewaysError || starting}
                      className="flex-1 transition-all duration-300"
                      data-testid="button-check"
                    >
                      {starting ? (
                        <>
                          <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-1 animate-spin" />
                          Starting...
                        </>
                      ) : (
                        <>
                          <Zap className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
                          Check
                        </>
                      )}
                    </Button>
                  ) : (
                    <Button
                      onClick={handleStop}
                      variant="destructive"
                      className="flex-1 transition-all duration-300"
                      disabled={stopping}
                      data-testid="button-stop"
                    >
                      {stopping ? (
                        <>
                          <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-1 animate-spin" />
                          Stopping...
                        </>
                      ) : (
                        <>
                          <XCircle className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
                          Stop
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="animate-fade-in-up" style={{ animationDelay: "200ms" }}>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <span className="lg:text-xl">📋</span>
                  Checking Logs
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                <div className="max-h-[140px] lg:max-h-[200px] overflow-y-auto" data-testid="log-area">
                  {logs.length === 0 ? (
                    <p className="text-xs lg:text-sm text-muted-foreground py-2">No logs yet</p>
                  ) : (
                    <div className="flex flex-col gap-0.5 lg:gap-1 font-mono text-[11px] lg:text-sm">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-2 ${getLogColor(log.type)}`} data-testid={`log-entry-${i}`}>
                          <span className="text-muted-foreground shrink-0">{log.time}</span>
                          <span className="break-all">{log.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="lg:col-span-3 flex flex-col gap-4 lg:gap-6">
            <div className="grid grid-cols-4 gap-2 lg:gap-4">
              <Card className={`p-3 lg:p-5 transition-all duration-500 hover:scale-[1.02] hover:shadow-md ${charged > 0 ? "ring-1 ring-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.15)]" : ""}`}>
                <div className="flex flex-col items-center gap-1 lg:gap-2">
                  <span className="text-base lg:text-2xl">💳</span>
                  <span className="text-lg lg:text-2xl font-bold text-emerald-400 animate-count-up" data-testid="text-charged-count">{charged}</span>
                  <span className="text-[10px] lg:text-xs text-muted-foreground">Charged</span>
                </div>
              </Card>
              <Card className={`p-3 lg:p-5 transition-all duration-500 hover:scale-[1.02] hover:shadow-md ${approved > 0 ? "ring-1 ring-blue-500/30" : ""}`}>
                <div className="flex flex-col items-center gap-1 lg:gap-2">
                  <span className="text-base lg:text-2xl">✅</span>
                  <span className="text-lg lg:text-2xl font-bold text-blue-400 animate-count-up" data-testid="text-approved-count">{approved}</span>
                  <span className="text-[10px] lg:text-xs text-muted-foreground">Approved</span>
                </div>
              </Card>
              <Card className="p-3 lg:p-5 transition-all duration-500 hover:scale-[1.02] hover:shadow-md">
                <div className="flex flex-col items-center gap-1 lg:gap-2">
                  <span className="text-base lg:text-2xl">❌</span>
                  <span className="text-lg lg:text-2xl font-bold text-red-400 animate-count-up" data-testid="text-declined-count">{declined}</span>
                  <span className="text-[10px] lg:text-xs text-muted-foreground">Declined</span>
                </div>
              </Card>
              <Card className="p-3 lg:p-5 transition-all duration-500 hover:scale-[1.02] hover:shadow-md">
                <div className="flex flex-col items-center gap-1 lg:gap-2">
                  <span className="text-base lg:text-2xl">⚠️</span>
                  <span className="text-lg lg:text-2xl font-bold text-yellow-400 animate-count-up" data-testid="text-error-count">{errors}</span>
                  <span className="text-[10px] lg:text-xs text-muted-foreground">Error</span>
                </div>
              </Card>
            </div>

            <Card className="flex flex-col animate-fade-in-up" style={{ animationDelay: "100ms" }}>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between gap-2">
                <CardTitle className="text-sm lg:text-lg"><span className="lg:text-xl">📊</span> Results</CardTitle>
                <div className="flex items-center gap-1 flex-wrap">
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={copyResults}
                    disabled={results.length === 0}
                    className="transition-all duration-300"
                    data-testid="button-copy-all"
                  >
                    <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={clearResults}
                    disabled={results.length === 0 || checking}
                    className="transition-all duration-300"
                    data-testid="button-clear"
                  >
                    <Trash2 className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                {results.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                    <CreditCard className="w-8 h-8 lg:w-10 lg:h-10 mb-3 opacity-30" />
                    <p className="text-sm lg:text-base">No results yet</p>
                    <p className="text-xs lg:text-sm mt-1">Select a gateway and enter cards to start</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 lg:gap-3 max-h-[60vh] overflow-y-auto">
                    {results.map((r, i) => {
                      const gatewayInfo = gateways.find(g => g.id === selectedGateway);
                      const gatewayName = r.gateway || gatewayInfo?.name || selectedGateway;
                      const chargeAmount = r.response ? extractChargeAmount(r.response) : null;
                      const isHit = r.status === "charged" || r.status === "approved";

                      return (
                        <div
                          key={r.id}
                          className={`rounded-lg border p-3 lg:p-4 animate-slide-in-right transition-all duration-300 ${getStatusBg(r.status)} ${isHit && r.status === "charged" ? "ring-1 ring-emerald-500/30" : ""}`}
                          style={{ animationDelay: `${Math.min(i * 50, 300)}ms` }}
                          data-testid={`result-item-${i}`}
                        >
                          <div className="flex items-start gap-2.5 lg:gap-3">
                            <div className={`mt-0.5 ${getStatusColor(r.status)} ${r.status === "charged" ? "animate-count-up" : ""}`}>
                              {getStatusIcon(r.status)}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap mb-1">
                                <span className={`text-xs lg:text-sm font-bold ${getStatusColor(r.status)}`}>
                                  {getStatusLabel(r.status)}
                                </span>
                                {chargeAmount && r.status === "charged" && (
                                  <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-[10px] lg:text-xs font-bold">
                                    💰 {chargeAmount}
                                  </Badge>
                                )}
                              </div>
                              <code className="text-xs lg:text-sm font-mono break-all text-foreground/80" data-testid={`text-card-${i}`}>
                                {getStatusEmoji(r.status)} {r.card}
                              </code>
                              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                                <Badge variant="outline" className="text-[9px] lg:text-xs font-medium">
                                  🌐 {gatewayName}
                                </Badge>
                                {r.status === "charged" && (
                                  <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-[9px] lg:text-xs">
                                    ⚡ HIT
                                  </Badge>
                                )}
                              </div>
                              {r.response && r.status !== "checking" && (
                                <p className="text-[11px] lg:text-sm text-muted-foreground mt-1.5 break-all" data-testid={`text-response-${i}`}>
                                  📋 {r.response}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </PageTransition>

      <Dialog open={showSkoolPopup} onOpenChange={setShowSkoolPopup}>
        <DialogContent className="sm:max-w-md" data-testid="dialog-skool-activation">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg">
              <ShieldOff className="w-5 h-5 text-red-500" />
              Activate The Gateway First
            </DialogTitle>
            <DialogDescription>
              This gateway requires a Skool account to work. Follow the steps below to activate it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-3">
              <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
                <span className="flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary font-bold text-sm shrink-0">1</span>
                <div>
                  <p className="font-medium text-sm">Create a Skool account</p>
                  <p className="text-xs text-muted-foreground mt-0.5">Go to skool.com and sign up for a free account</p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
                <span className="flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary font-bold text-sm shrink-0">2</span>
                <div>
                  <p className="font-medium text-sm">Add your account to the bot</p>
                  <p className="text-xs text-muted-foreground mt-0.5">Use this command in the Telegram bot:</p>
                  <code className="inline-block mt-1.5 px-3 py-1.5 bg-background border rounded text-xs font-mono">/addskool youremail:yourpass</code>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
              <p className="text-xs text-emerald-400">Once your Skool account is added, this gateway will be activated automatically</p>
            </div>
          </div>
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button
              variant="outline"
              onClick={() => setShowSkoolPopup(false)}
              data-testid="button-close-skool-popup"
            >
              Close
            </Button>
            <Button
              onClick={() => window.open("https://www.skool.com/signup", "_blank")}
              className="gap-2"
              data-testid="button-goto-skool"
            >
              <ExternalLink className="w-4 h-4" />
              Go to Skool.com
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
