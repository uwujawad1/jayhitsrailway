import { useState, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ShoppingCart, ArrowLeft, Loader2, Plus, Trash2, XCircle,
  Globe, ShieldCheck, CheckCircle2, AlertCircle, Copy, Zap, Eye, X,
  Square, RefreshCw
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, apiUrl } from "@/lib/queryClient";

interface JobResult {
  id: string;
  card: string;
  status: string;
  response: string;
  timestamp: number;
}

interface JobSummary {
  jobId: string;
  status: "running" | "completed" | "stopped";
  gateway: string;
  totalCards: number;
  processedCards: number;
  charged: number;
  approved: number;
  declined: number;
  errors: number;
  createdAt: number;
  completedAt?: number;
}

interface JobDetail {
  jobId: string;
  status: "running" | "completed" | "stopped";
  gateway: string;
  totalCards: number;
  processedCards: number;
  results: JobResult[];
  allResultsCount: number;
  createdAt: number;
  completedAt?: number;
}

type ResultTab = "all" | "charged" | "approved" | "declined" | "error";

function getStatusColor(status: string) {
  switch (status) {
    case "charged": return "text-emerald-400";
    case "approved": return "text-blue-400";
    case "declined": return "text-red-400";
    case "checking": return "text-yellow-400";
    default: return "text-red-400";
  }
}

function getStatusBg(status: string) {
  switch (status) {
    case "charged": return "bg-emerald-500/10 border-emerald-500/20";
    case "approved": return "bg-blue-500/10 border-blue-500/20";
    case "declined": return "bg-red-500/10 border-red-500/20";
    case "checking": return "bg-yellow-500/10 border-yellow-500/20";
    default: return "bg-red-500/10 border-red-500/20";
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case "charged": return <ShieldCheck className="w-3.5 h-3.5 lg:w-4 lg:h-4 text-emerald-400" />;
    case "approved": return <CheckCircle2 className="w-3.5 h-3.5 lg:w-4 lg:h-4 text-blue-400" />;
    case "checking": return <Loader2 className="w-3.5 h-3.5 lg:w-4 lg:h-4 text-yellow-400 animate-spin" />;
    default: return <XCircle className="w-3.5 h-3.5 lg:w-4 lg:h-4 text-red-400" />;
  }
}

function formatDuration(ms: number) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

export default function AutoShopifyPage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [showSites, setShowSites] = useState(false);
  const [showAddSite, setShowAddSite] = useState(false);
  const [newSiteUrl, setNewSiteUrl] = useState("");
  const [cardInput, setCardInput] = useState("");
  const [activeTab, setActiveTab] = useState<ResultTab>("all");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobResults, setJobResults] = useState<JobResult[]>([]);
  const [jobDetail, setJobDetail] = useState<JobDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const seenCountRef = useRef<number>(0);

  const { data: sitesData, isLoading: sitesLoading } = useQuery<{ sites: string[]; count: number }>({
    queryKey: ["/api/shopify/sites"],
  });

  const { data: existingJobs } = useQuery<JobSummary[]>({
    queryKey: ["/api/check/batch"],
    refetchInterval: activeJobId ? false : 10000,
  });

  const sites = sitesData?.sites || [];

  useEffect(() => {
    if (!activeJobId && existingJobs && existingJobs.length > 0) {
      const runningJob = existingJobs.find(j => j.status === "running");
      if (runningJob) {
        setActiveJobId(runningJob.jobId);
      }
    }
  }, [existingJobs, activeJobId]);

  useEffect(() => {
    if (!activeJobId) return;

    const poll = async () => {
      try {
        const res = await fetch(apiUrl(`/api/check/batch/${activeJobId}?after=${seenCountRef.current}`), {
          credentials: "include",
        });
        if (!res.ok) {
          if (res.status === 404) {
            setActiveJobId(null);
            setJobDetail(null);
            if (pollRef.current) clearInterval(pollRef.current);
          }
          return;
        }
        const data: JobDetail = await res.json();
        setJobDetail(data);

        if (data.results.length > 0) {
          seenCountRef.current = data.allResultsCount;
          setJobResults(prev => [...data.results, ...prev]);
        }

        if (data.status !== "running") {
          if (pollRef.current) clearInterval(pollRef.current);
          queryClient.invalidateQueries({ queryKey: ["/api/check/batch"] });
        }
      } catch {}
    };

    poll();
    pollRef.current = setInterval(poll, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [activeJobId, queryClient]);

  const chargedCount = jobResults.filter(r => r.status === "charged").length;
  const approvedCount = jobResults.filter(r => r.status === "approved").length;
  const declinedCount = jobResults.filter(r => r.status === "declined").length;
  const errorCount = jobResults.filter(r => r.status === "error" || r.status === "unknown").length;

  const filteredResults = activeTab === "all"
    ? jobResults
    : activeTab === "error"
      ? jobResults.filter(r => r.status === "error" || r.status === "unknown")
      : jobResults.filter(r => r.status === activeTab);

  const addSites = async () => {
    const urls = newSiteUrl.split("\n").map(u => u.trim()).filter(u => u.length > 0);
    if (urls.length === 0) return;
    try {
      const res = await apiRequest("POST", "/api/shopify/sites", { urls });
      const data = await res.json();
      toast({ title: `Added ${data.count} site(s)` });
      setNewSiteUrl("");
      setShowAddSite(false);
      queryClient.invalidateQueries({ queryKey: ["/api/shopify/sites"] });
    } catch (err: any) {
      toast({ title: err.message || "Failed to add sites", variant: "destructive" });
    }
  };

  const removeSite = async (url: string) => {
    try {
      await apiRequest("DELETE", "/api/shopify/sites", { url });
      queryClient.invalidateQueries({ queryKey: ["/api/shopify/sites"] });
      toast({ title: "Site removed" });
    } catch (err: any) {
      toast({ title: err.message || "Failed to remove", variant: "destructive" });
    }
  };

  const clearAll = async () => {
    try {
      const res = await apiRequest("DELETE", "/api/shopify/sites/all");
      const data = await res.json();
      queryClient.invalidateQueries({ queryKey: ["/api/shopify/sites"] });
      toast({ title: `Cleared ${data.cleared} site(s)` });
    } catch (err: any) {
      toast({ title: err.message || "Failed to clear", variant: "destructive" });
    }
  };

  const handleCheck = async () => {
    const cards = cardInput
      .split("\n")
      .map(c => c.trim())
      .filter(c => c && /^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(c));

    if (cards.length === 0) {
      toast({ title: "Enter valid cards", description: "Format: CC|MM|YY|CVV", variant: "destructive" });
      return;
    }

    setStarting(true);
    try {
      const res = await apiRequest("POST", "/api/check/batch", { gateway: "shp", cards });
      const data = await res.json();
      setActiveJobId(data.jobId);
      setJobResults([]);
      setJobDetail(null);
      seenCountRef.current = 0;
      setActiveTab("all");
      setCardInput("");
      toast({ title: `Started checking ${data.totalCards} cards`, description: "You can leave this page — checking continues in background" });
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
    }
    setStarting(false);
  };

  const handleStop = async () => {
    if (!activeJobId) return;
    setStopping(true);
    try {
      await apiRequest("DELETE", `/api/check/batch/${activeJobId}`);
      toast({ title: "Stopping check..." });
    } catch (err: any) {
      toast({ title: "Failed to stop", variant: "destructive" });
    }
    setStopping(false);
  };

  const handleNewCheck = () => {
    setActiveJobId(null);
    setJobResults([]);
    setJobDetail(null);
    seenCountRef.current = 0;
    setActiveTab("all");
  };

  const copyResults = (tab?: ResultTab) => {
    const toCopy = tab && tab !== "all"
      ? (tab === "error"
        ? jobResults.filter(r => r.status === "error" || r.status === "unknown")
        : jobResults.filter(r => r.status === tab))
      : jobResults;
    const text = toCopy.map(r => `${r.card} | ${r.status.toUpperCase()} | ${r.response}`).join("\n");
    navigator.clipboard.writeText(text);
    toast({ title: `Copied ${toCopy.length} result(s)` });
  };

  const copyCards = (status: string) => {
    const cards = jobResults
      .filter(r => r.status === status)
      .map(r => r.card);
    navigator.clipboard.writeText(cards.join("\n"));
    toast({ title: `Copied ${cards.length} ${status} card(s)` });
  };

  const isRunning = jobDetail?.status === "running";
  const hasJob = activeJobId && jobDetail;

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <div className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back" className="transition-all duration-300">
          <ArrowLeft className="w-4 h-4 lg:w-5 lg:h-5" />
        </Button>
        <ShoppingCart className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Auto Shopify</h1>
        {isRunning && jobDetail && (
          <Badge variant="secondary" className="text-xs lg:text-sm">
            <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1 animate-spin" />
            {jobDetail.processedCards}/{jobDetail.totalCards}
          </Badge>
        )}
        {jobDetail && jobDetail.status !== "running" && (
          <Badge variant={jobDetail.status === "completed" ? "default" : "secondary"} className="text-xs lg:text-sm">
            {jobDetail.status === "completed" ? "Done" : "Stopped"} — {jobDetail.allResultsCount} results
          </Badge>
        )}
      </div>

      <div className="flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <div className="flex gap-2 lg:gap-3">
            <Button
              variant={showSites ? "default" : "outline"}
              className="flex-1 transition-all duration-300"
              onClick={() => { setShowSites(!showSites); setShowAddSite(false); }}
              data-testid="button-view-sites"
            >
              <Eye className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
              View Sites
              <Badge variant="secondary" className="ml-2 text-xs lg:text-sm">{sites.length}</Badge>
            </Button>
            <Button
              variant={showAddSite ? "default" : "outline"}
              className="flex-1 transition-all duration-300"
              onClick={() => { setShowAddSite(!showAddSite); setShowSites(false); }}
              data-testid="button-add-site-toggle"
            >
              <Plus className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
              Add Site
            </Button>
          </div>

          {showSites && (
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Globe className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                    Your Shopify Sites
                    <Badge variant="secondary" className="text-xs lg:text-sm">{sites.length}</Badge>
                  </span>
                  <div className="flex items-center gap-1">
                    {sites.length > 0 && (
                      <Button size="sm" variant="ghost" className="text-destructive text-xs lg:text-sm transition-all duration-300" onClick={clearAll} data-testid="button-clear-sites">
                        <Trash2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />
                        Clear All
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" onClick={() => setShowSites(false)} data-testid="button-close-sites">
                      <X className="w-4 h-4 lg:w-5 lg:h-5" />
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                {sitesLoading ? (
                  <div className="flex items-center gap-2 text-xs lg:text-sm text-muted-foreground py-2">
                    <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" />
                    Loading sites...
                  </div>
                ) : sites.length === 0 ? (
                  <p className="text-xs lg:text-sm text-muted-foreground py-2">No sites added yet. Click "Add Site" to add Shopify sites.</p>
                ) : (
                  <div className="flex flex-col gap-1 lg:gap-2 max-h-[300px] overflow-y-auto">
                    {sites.map((site, i) => (
                      <div key={i} className="flex items-center justify-between gap-2 rounded-md border px-3 lg:px-4 py-1.5 lg:py-2 bg-muted/30 transition-all duration-300 hover:bg-muted/50" data-testid={`site-item-${i}`}>
                        <span className="text-xs lg:text-sm font-mono break-all">{site}</span>
                        <Button size="icon" variant="ghost" className="shrink-0 h-6 w-6 lg:h-7 lg:w-7 transition-all duration-300" onClick={() => removeSite(site)} data-testid={`button-remove-site-${i}`}>
                          <XCircle className="w-3 h-3 lg:w-4 lg:h-4 text-destructive" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {showAddSite && (
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Plus className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                    Add Shopify Sites
                  </span>
                  <Button size="icon" variant="ghost" onClick={() => setShowAddSite(false)} data-testid="button-close-add">
                    <X className="w-4 h-4 lg:w-5 lg:h-5" />
                  </Button>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
                <Textarea
                  placeholder={"shopify-store.com\nanother-store.myshopify.com"}
                  value={newSiteUrl}
                  onChange={e => setNewSiteUrl(e.target.value)}
                  className="min-h-[80px] lg:min-h-[100px] font-mono text-xs lg:text-sm resize-none"
                  data-testid="input-new-site"
                />
                <Button onClick={addSites} disabled={!newSiteUrl.trim()} className="w-full transition-all duration-300" data-testid="button-add-site">
                  <Plus className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
                  Add Sites
                </Button>
                <p className="text-[10px] lg:text-xs text-muted-foreground">Add one site per line. Sites are used by the Shopify Native gateway to check cards.</p>
              </CardContent>
            </Card>
          )}

          {!hasJob && (
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <Zap className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                  Check Cards
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
                <Textarea
                  placeholder={"4111111111111111|12|25|123\n5500000000000004|06|26|456"}
                  value={cardInput}
                  onChange={e => setCardInput(e.target.value)}
                  disabled={starting}
                  className="min-h-[120px] lg:min-h-[150px] font-mono text-xs lg:text-sm resize-none"
                  data-testid="input-cards"
                />
                <div className="flex items-center justify-between text-[10px] lg:text-xs text-muted-foreground">
                  <span>
                    {cardInput.trim() ? `${cardInput.trim().split("\n").filter(c => /^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(c.trim())).length} valid cards` : "Paste cards (CC|MM|YY|CVV)"}
                  </span>
                  <span>Runs in background — you can leave this page</span>
                </div>
                <Button onClick={handleCheck} disabled={!cardInput.trim() || starting} className="w-full transition-all duration-300" data-testid="button-check">
                  {starting ? (
                    <>
                      <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-1 animate-spin" />
                      Starting...
                    </>
                  ) : (
                    <>
                      <ShoppingCart className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />
                      Check via Shopify
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          )}

          {hasJob && (
            <>
              <Card className="animate-fade-in-up">
                <CardContent className="p-4 lg:p-6 flex items-center justify-between">
                  <div className="flex items-center gap-3 lg:gap-4">
                    {isRunning ? (
                      <Loader2 className="w-5 h-5 lg:w-6 lg:h-6 text-primary animate-spin" />
                    ) : (
                      <CheckCircle2 className={`w-5 h-5 lg:w-6 lg:h-6 ${jobDetail.status === "completed" ? "text-emerald-400" : "text-muted-foreground"}`} />
                    )}
                    <div>
                      <p className="text-sm lg:text-base font-medium">
                        {isRunning ? "Checking in progress..." : jobDetail.status === "completed" ? "Check Complete" : "Check Stopped"}
                      </p>
                      <p className="text-[11px] lg:text-sm text-muted-foreground">
                        {jobDetail.processedCards}/{jobDetail.totalCards} cards processed
                        {jobDetail.completedAt && ` · ${formatDuration(jobDetail.completedAt - jobDetail.createdAt)}`}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {isRunning ? (
                      <Button size="sm" variant="destructive" onClick={handleStop} disabled={stopping} className="transition-all duration-300" data-testid="button-stop">
                        {stopping ? <Loader2 className="w-3.5 h-3.5 lg:w-4 lg:h-4 animate-spin" /> : <Square className="w-3.5 h-3.5 lg:w-4 lg:h-4" />}
                        <span className="ml-1">Stop</span>
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={handleNewCheck} className="transition-all duration-300" data-testid="button-new-check">
                        <RefreshCw className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                        New Check
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>

              <div className="grid grid-cols-4 gap-2 lg:gap-4">
                <Card
                  className={`p-3 lg:p-5 cursor-pointer transition-all duration-300 hover:scale-[1.02] hover:shadow-md ${activeTab === "charged" ? "ring-2 ring-emerald-400/50" : ""}`}
                  onClick={() => setActiveTab(activeTab === "charged" ? "all" : "charged")}
                  data-testid="tab-charged"
                >
                  <div className="flex flex-col items-center gap-1 lg:gap-2">
                    <ShieldCheck className="w-4 h-4 lg:w-5 lg:h-5 text-emerald-400 transition-transform duration-300 hover:scale-110" />
                    <span className="text-lg lg:text-2xl font-bold text-emerald-400" data-testid="text-charged-count">{chargedCount}</span>
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] lg:text-xs text-muted-foreground">Charged</span>
                      {chargedCount > 0 && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-4 w-4 lg:h-5 lg:w-5"
                          onClick={e => { e.stopPropagation(); copyCards("charged"); }}
                          data-testid="button-copy-charged"
                        >
                          <Copy className="w-2.5 h-2.5 lg:w-3 lg:h-3" />
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
                <Card
                  className={`p-3 lg:p-5 cursor-pointer transition-all duration-300 hover:scale-[1.02] hover:shadow-md ${activeTab === "approved" ? "ring-2 ring-blue-400/50" : ""}`}
                  onClick={() => setActiveTab(activeTab === "approved" ? "all" : "approved")}
                  data-testid="tab-approved"
                >
                  <div className="flex flex-col items-center gap-1 lg:gap-2">
                    <CheckCircle2 className="w-4 h-4 lg:w-5 lg:h-5 text-blue-400 transition-transform duration-300 hover:scale-110" />
                    <span className="text-lg lg:text-2xl font-bold text-blue-400" data-testid="text-approved-count">{approvedCount}</span>
                    <div className="flex items-center gap-1">
                      <span className="text-[10px] lg:text-xs text-muted-foreground">Approved</span>
                      {approvedCount > 0 && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-4 w-4 lg:h-5 lg:w-5"
                          onClick={e => { e.stopPropagation(); copyCards("approved"); }}
                          data-testid="button-copy-approved"
                        >
                          <Copy className="w-2.5 h-2.5 lg:w-3 lg:h-3" />
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
                <Card
                  className={`p-3 lg:p-5 cursor-pointer transition-all duration-300 hover:scale-[1.02] hover:shadow-md ${activeTab === "declined" ? "ring-2 ring-red-400/50" : ""}`}
                  onClick={() => setActiveTab(activeTab === "declined" ? "all" : "declined")}
                  data-testid="tab-declined"
                >
                  <div className="flex flex-col items-center gap-1 lg:gap-2">
                    <XCircle className="w-4 h-4 lg:w-5 lg:h-5 text-red-400 transition-transform duration-300 hover:scale-110" />
                    <span className="text-lg lg:text-2xl font-bold text-red-400" data-testid="text-declined-count">{declinedCount}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Declined</span>
                  </div>
                </Card>
                <Card
                  className={`p-3 lg:p-5 cursor-pointer transition-all duration-300 hover:scale-[1.02] hover:shadow-md ${activeTab === "error" ? "ring-2 ring-yellow-400/50" : ""}`}
                  onClick={() => setActiveTab(activeTab === "error" ? "all" : "error")}
                  data-testid="tab-error"
                >
                  <div className="flex flex-col items-center gap-1 lg:gap-2">
                    <AlertCircle className="w-4 h-4 lg:w-5 lg:h-5 text-yellow-400 transition-transform duration-300 hover:scale-110" />
                    <span className="text-lg lg:text-2xl font-bold text-yellow-400" data-testid="text-error-count">{errorCount}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Error</span>
                  </div>
                </Card>
              </div>

              <Card className="animate-fade-in-up">
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    Results
                    {activeTab !== "all" && (
                      <Badge variant="secondary" className="text-xs lg:text-sm capitalize">{activeTab}</Badge>
                    )}
                    <span className="text-xs lg:text-sm text-muted-foreground font-normal">({filteredResults.length})</span>
                  </CardTitle>
                  <div className="flex items-center gap-1">
                    {activeTab !== "all" && (
                      <Button size="sm" variant="ghost" className="text-xs lg:text-sm transition-all duration-300" onClick={() => setActiveTab("all")} data-testid="button-show-all">
                        Show All
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" onClick={() => copyResults(activeTab)} disabled={filteredResults.length === 0} className="transition-all duration-300" data-testid="button-copy-results">
                      <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                  <div className="flex flex-col gap-2 lg:gap-3 max-h-[60vh] overflow-y-auto">
                    {filteredResults.length === 0 ? (
                      <p className="text-xs lg:text-sm text-muted-foreground py-4 text-center">
                        {isRunning ? "Waiting for results..." : `No ${activeTab !== "all" ? activeTab : ""} results`}
                      </p>
                    ) : (
                      filteredResults.map((r, i) => (
                        <div key={r.id} className={`rounded-md border p-3 lg:p-4 ${getStatusBg(r.status)} transition-all duration-300`} data-testid={`result-item-${i}`}>
                          <div className="flex items-start gap-2 lg:gap-3">
                            <div className="mt-0.5">
                              {getStatusIcon(r.status)}
                            </div>
                            <div className="flex-1 min-w-0">
                              <code className="text-xs lg:text-sm font-mono break-all" data-testid={`text-card-${i}`}>{r.card}</code>
                              <p className={`text-xs lg:text-sm font-semibold mt-1 ${getStatusColor(r.status)}`}>
                                {r.status.toUpperCase()}
                              </p>
                              {r.response && (
                                <p className="text-xs lg:text-sm text-muted-foreground mt-0.5 break-all" data-testid={`text-response-${i}`}>
                                  - {r.response}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            </>
          )}

          {!hasJob && existingJobs && existingJobs.filter(j => j.status !== "running").length > 0 && (
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg">Recent Jobs</CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                <div className="flex flex-col gap-2 lg:gap-3">
                  {existingJobs.filter(j => j.status !== "running").slice(0, 5).map(job => (
                    <div
                      key={job.jobId}
                      className="flex items-center justify-between rounded-md border p-3 lg:p-4 bg-muted/30 cursor-pointer hover:bg-muted/50 transition-all duration-300 hover:scale-[1.01]"
                      onClick={() => {
                        setActiveJobId(job.jobId);
                        setJobResults([]);
                        seenCountRef.current = 0;
                      }}
                      data-testid={`job-${job.jobId}`}
                    >
                      <div>
                        <p className="text-xs lg:text-sm font-medium">
                          {job.totalCards} cards · {job.gateway.toUpperCase()}
                          <Badge variant={job.status === "completed" ? "default" : "secondary"} className="text-[10px] lg:text-xs ml-2">
                            {job.status}
                          </Badge>
                        </p>
                        <p className="text-[10px] lg:text-xs text-muted-foreground mt-0.5">
                          {new Date(job.createdAt).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 text-[11px] lg:text-sm">
                        {job.charged > 0 && <span className="text-emerald-400 font-semibold">{job.charged} charged</span>}
                        {job.approved > 0 && <span className="text-blue-400 font-semibold">{job.approved} approved</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
