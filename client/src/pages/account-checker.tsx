import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation, useSearch } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  ArrowLeft, Loader2, Copy, CheckCircle2, XCircle, AlertCircle,
  Gamepad2, Shield, BookOpen, Tv, UserCheck, Trash2, Play, Square,
  Download, Clock, Ban
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";

const CHECKERS = [
  { id: "crunchyroll", label: "Crunchyroll", icon: Tv, color: "text-orange-400" },
  { id: "xbox", label: "Xbox", icon: Gamepad2, color: "text-green-400" },
  { id: "cyberghost", label: "CyberGhost VPN", icon: Shield, color: "text-yellow-400" },
  { id: "duolingo", label: "Duolingo", icon: BookOpen, color: "text-emerald-400" },
  { id: "hoichoi", label: "Hoichoi", icon: Tv, color: "text-purple-400" },
];

interface CheckResult {
  id: string;
  checker: string;
  combo: string;
  status: string;
  capture: Record<string, string>;
  timestamp: number;
}

function extractCombos(text: string): string[] {
  const combos: string[] = [];
  const seen = new Set<string>();
  const emailComboRegex = /([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}):([^\s,;|]+)/g;
  let match;
  while ((match = emailComboRegex.exec(text)) !== null) {
    const combo = `${match[1]}:${match[2]}`;
    const key = combo.toLowerCase();
    if (!seen.has(key) && match[2].length >= 1) {
      seen.add(key);
      combos.push(combo);
    }
  }

  if (combos.length === 0) {
    const lines = text.split(/[\n\r]+/).map(l => l.trim()).filter(Boolean);
    for (const line of lines) {
      const parts = line.split(":");
      if (parts.length >= 2) {
        const user = parts[0].trim();
        const pass = parts.slice(1).join(":").trim();
        if (user.length >= 3 && pass.length >= 1) {
          const combo = `${user}:${pass}`;
          const key = combo.toLowerCase();
          if (!seen.has(key)) {
            seen.add(key);
            combos.push(combo);
          }
        }
      }
    }
  }

  return combos;
}

function displayStatus(status: string) {
  if (status === "FAIL") return "INVALID";
  if (status === "checking") return "Checking...";
  return status;
}

function getStatusColor(status: string) {
  switch (status) {
    case "HIT": return "text-emerald-400";
    case "FREE": return "text-blue-400";
    case "CUSTOM": return "text-amber-400";
    case "2FA": return "text-purple-400";
    case "FAIL": return "text-red-400";
    default: return "text-muted-foreground";
  }
}

function getStatusBg(status: string) {
  switch (status) {
    case "HIT": return "bg-emerald-500/10 border-emerald-500/20";
    case "FREE": return "bg-blue-500/10 border-blue-500/20";
    case "CUSTOM": return "bg-amber-500/10 border-amber-500/20";
    case "2FA": return "bg-purple-500/10 border-purple-500/20";
    case "FAIL": return "bg-red-500/10 border-red-500/20";
    default: return "bg-muted/50 border-border";
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case "HIT": return <CheckCircle2 className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "FREE": return <UserCheck className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "CUSTOM": return <AlertCircle className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "2FA": return <Shield className="w-4 h-4 lg:w-5 lg:h-5" />;
    case "FAIL": return <Ban className="w-4 h-4 lg:w-5 lg:h-5" />;
    default: return <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 animate-spin" />;
  }
}

function statusBadgeClass(status: string) {
  switch (status) {
    case "HIT": return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    case "FREE": return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    case "FAIL": return "bg-red-500/20 text-red-400 border-red-500/30";
    case "checking": return "bg-muted text-muted-foreground";
    case "skipped": return "bg-muted text-muted-foreground";
    default: return "bg-amber-500/20 text-amber-400 border-amber-500/30";
  }
}

interface TierInfo {
  tier: string;
  limits: { massAccountMax: number };
}

export default function AccountCheckerPage() {
  const [, navigate] = useLocation();
  const searchString = useSearch();
  const { toast } = useToast();
  const [selectedChecker, setSelectedChecker] = useState<string>("crunchyroll");
  const [comboInput, setComboInput] = useState("");
  const [isChecking, setIsChecking] = useState(false);
  const [results, setResults] = useState<CheckResult[]>([]);
  const [extractedCount, setExtractedCount] = useState(0);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const stopRef = useRef(false);
  const resultsEndRef = useRef<HTMLDivElement>(null);

  const { data: checkerStatuses } = useQuery<Record<string, boolean>>({
    queryKey: ["/api/account-checkers/status"],
  });

  const { data: tierInfo } = useQuery<TierInfo>({
    queryKey: ["/api/user/tier"],
  });

  const massLimit = tierInfo?.limits?.massAccountMax ?? 1;
  const tier = tierInfo?.tier || "free";

  const enabledCheckers = CHECKERS.filter(c => !checkerStatuses || checkerStatuses[c.id] !== false);

  useEffect(() => {
    const params = new URLSearchParams(searchString);
    const checker = params.get("checker");
    if (checker && enabledCheckers.find(c => c.id === checker)) {
      setSelectedChecker(checker);
    } else if (enabledCheckers.length > 0 && !enabledCheckers.find(c => c.id === selectedChecker)) {
      setSelectedChecker(enabledCheckers[0].id);
    }
  }, [searchString, checkerStatuses]);

  useEffect(() => {
    const combos = extractCombos(comboInput);
    setExtractedCount(combos.length);
  }, [comboInput]);

  const activeChecker = CHECKERS.find(c => c.id === selectedChecker);

  const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

  const checkSingle = useCallback(async (checker: string, combo: string, tempId: string): Promise<string> => {
    const maxRetries = 3;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await apiRequest("POST", "/api/tools/account-check", { checker, combo });
        const data = await response.json();

        if (data.status === "error" && data.message?.includes("Rate limit")) {
          if (attempt < maxRetries - 1) {
            await delay(3000);
            continue;
          }
        }

        const finalStatus = data.status === "error" ? "error" : data.status;
        setResults(prev => prev.map(r => r.id === tempId ? {
          ...r,
          status: finalStatus,
          capture: data.capture || {},
        } : r));
        return finalStatus;
      } catch (err: any) {
        if (attempt < maxRetries - 1) {
          await delay(2000);
          continue;
        }
        setResults(prev => prev.map(r => r.id === tempId ? {
          ...r,
          status: "error",
          capture: { error: err.message || "Check failed" },
        } : r));
        return "error";
      }
    }
    return "error";
  }, []);

  const handleCheck = async () => {
    if (!selectedChecker || !comboInput.trim()) return;

    const combos = extractCombos(comboInput);
    if (combos.length === 0) {
      toast({ title: "No combos found", description: "Paste email:password combos to check", variant: "destructive" });
      return;
    }

    if (combos.length > massLimit) {
      toast({
        title: `Mass check limit: ${massLimit} combos`,
        description: tier === "free"
          ? "Free plan allows single check only. Upgrade to Silver for mass checking."
          : `Your ${tier} plan allows max ${massLimit} combos at once.`,
        variant: "destructive",
      });
      return;
    }

    setIsChecking(true);
    stopRef.current = false;
    setProgress({ done: 0, total: combos.length });

    const pendingResults: CheckResult[] = combos.map((combo, i) => ({
      id: `check-${Date.now()}-${i}`,
      checker: selectedChecker,
      combo,
      status: "queued",
      capture: {},
      timestamp: Date.now(),
    }));

    setResults(prev => [...pendingResults, ...prev]);

    let hits = 0;
    let doneCount = 0;
    for (let i = 0; i < combos.length; i++) {
      if (stopRef.current) break;

      const r = pendingResults[i];
      setResults(prev => prev.map(x => x.id === r.id ? { ...x, status: "checking" } : x));

      const status = await checkSingle(selectedChecker, combos[i], r.id);
      if (status === "HIT") hits++;
      doneCount = i + 1;
      setProgress({ done: doneCount, total: combos.length });
    }

    if (stopRef.current) {
      setResults(prev => prev.map(r =>
        r.status === "queued" ? { ...r, status: "skipped", capture: { note: "Stopped by user" } } : r
      ));
      toast({ title: "Stopped", description: `Checked ${doneCount} of ${combos.length}` });
    } else if (hits > 0) {
      toast({ title: `Done! ${hits} hit${hits > 1 ? "s" : ""} found`, description: `Checked ${combos.length} combo${combos.length > 1 ? "s" : ""}` });
    } else {
      toast({ title: "Done", description: `Checked ${combos.length} combo${combos.length > 1 ? "s" : ""} — no hits` });
    }

    setIsChecking(false);
    setComboInput("");
  };

  const handleStop = () => {
    stopRef.current = true;
  };

  const copyResult = (result: CheckResult) => {
    const lines = [`${result.combo} | ${displayStatus(result.status)}`];
    for (const [k, v] of Object.entries(result.capture)) {
      lines.push(`${k}: ${v}`);
    }
    navigator.clipboard.writeText(lines.join("\n"));
    toast({ title: "Copied to clipboard" });
  };

  const exportHits = () => {
    const hits = results.filter(r => r.status === "HIT" || r.status === "CUSTOM" || r.status === "FREE");
    if (hits.length === 0) {
      toast({ title: "Nothing to export", variant: "destructive" });
      return;
    }
    const lines = hits.map(r => {
      const caps = Object.entries(r.capture).filter(([, v]) => v && v !== "N/A").map(([k, v]) => `${k}=${v}`).join(" | ");
      return `${r.combo} | ${displayStatus(r.status)}${caps ? ` | ${caps}` : ""}`;
    });
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedChecker}_hits_${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast({ title: `Exported ${hits.length} result${hits.length > 1 ? "s" : ""}` });
  };

  const statusCounts = results.reduce((acc, r) => {
    if (r.status !== "queued" && r.status !== "checking" && r.status !== "skipped") {
      const label = displayStatus(r.status);
      acc[label] = (acc[label] || 0) + 1;
    }
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <header className="flex items-center gap-2 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back" className="transition-all duration-300">
          <ArrowLeft className="w-5 h-5 lg:w-6 lg:h-6" />
        </Button>
        <div className="flex items-center gap-2">
          <UserCheck className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
          <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Accounts Checker</h1>
        </div>
      </header>

      <div className="flex-1 p-3 md:p-6 lg:p-8 overflow-y-auto">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <Card className="animate-fade-in-up">
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                <UserCheck className="w-4 h-4 lg:w-5 lg:h-5 text-primary transition-transform duration-300 hover:scale-110" />
                Checker
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3 flex flex-col gap-3 lg:gap-4">
              <Select value={selectedChecker} onValueChange={setSelectedChecker} disabled={isChecking}>
                <SelectTrigger data-testid="select-checker" className="w-full lg:text-sm">
                  <SelectValue placeholder="Select checker" />
                </SelectTrigger>
                <SelectContent>
                  {enabledCheckers.map((checker) => (
                    <SelectItem key={checker.id} value={checker.id} data-testid={`option-checker-${checker.id}`}>
                      <div className="flex items-center gap-2">
                        <checker.icon className={`w-4 h-4 lg:w-5 lg:h-5 ${checker.color}`} />
                        <span className="lg:text-sm">{checker.label}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="relative">
                <Textarea
                  placeholder={"Paste combos or any text containing email:password pairs...\n\nSmart detection auto-extracts combos from any text format.\nSupports: email:pass, user:pass, mixed text with combos"}
                  value={comboInput}
                  onChange={(e) => setComboInput(e.target.value)}
                  disabled={isChecking}
                  className="min-h-[120px] lg:min-h-[160px] font-mono text-xs lg:text-sm resize-y"
                  data-testid="input-combos"
                />
                {extractedCount > 0 && (
                  <Badge variant="secondary" className="absolute top-2 right-2 text-[10px] lg:text-xs" data-testid="badge-extracted-count">
                    {extractedCount} combo{extractedCount > 1 ? "s" : ""} detected
                  </Badge>
                )}
              </div>
              {massLimit === 1 && (
                <p className="text-[11px] lg:text-sm text-muted-foreground" data-testid="text-mass-limit-hint">
                  Free plan: single combo check only. Upgrade to Silver for mass checking (500).
                </p>
              )}
              {massLimit > 1 && extractedCount > massLimit && (
                <p className="text-[11px] lg:text-sm text-amber-400" data-testid="text-mass-limit-warning">
                  {tier} plan limit: max {massLimit} combos. You have {extractedCount} — reduce to continue.
                </p>
              )}

              <div className="flex items-center gap-2 lg:gap-3">
                {!isChecking ? (
                  <Button
                    onClick={handleCheck}
                    disabled={!comboInput.trim() || extractedCount === 0}
                    className="flex-1 transition-all duration-300 lg:text-sm lg:py-5"
                    data-testid="button-start-check"
                  >
                    <Play className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                    Check {extractedCount > 0 ? `${extractedCount} Combo${extractedCount > 1 ? "s" : ""}` : ""}
                  </Button>
                ) : (
                  <Button
                    onClick={handleStop}
                    variant="destructive"
                    className="flex-1 transition-all duration-300 lg:text-sm lg:py-5"
                    data-testid="button-stop-check"
                  >
                    <Square className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                    Stop ({progress.done}/{progress.total})
                  </Button>
                )}
              </div>

              <p className="text-[10px] lg:text-xs text-muted-foreground">
                Smart combo detection — paste any text, emails with passwords are auto-extracted. Proxies from Settings used automatically.
              </p>
            </CardContent>
          </Card>

          {results.length > 0 && (
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2 flex-wrap">
                    Results ({results.length})
                    {Object.entries(statusCounts).map(([label, count]) => (
                      <Badge key={label} variant="outline" className={`text-[9px] lg:text-xs ${
                        label === "HIT" ? "text-emerald-400" :
                        label === "FREE" ? "text-blue-400" :
                        label === "INVALID" ? "text-red-400" :
                        "text-amber-400"
                      }`}>
                        {label}: {count}
                      </Badge>
                    ))}
                  </CardTitle>
                  <div className="flex items-center gap-1 lg:gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 lg:h-8 px-2 lg:px-3 transition-all duration-300"
                      onClick={exportHits}
                      data-testid="button-export-hits"
                      title="Export hits"
                    >
                      <Download className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />
                      <span className="lg:text-sm">Export</span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive h-7 lg:h-8 px-2 lg:px-3 transition-all duration-300"
                      onClick={() => setResults([])}
                      data-testid="button-clear-results"
                    >
                      <Trash2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />
                      <span className="lg:text-sm">Clear</span>
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                <div className="flex flex-col gap-2 lg:gap-3 max-h-[60vh] overflow-y-auto pr-1">
                  {results.map((result) => {
                    const checkerInfo = CHECKERS.find(c => c.id === result.checker);
                    if (result.status === "queued") {
                      return (
                        <div key={result.id} className="rounded-lg border p-2 lg:p-3 bg-muted/20 border-border" data-testid={`result-${result.id}`}>
                          <div className="flex items-center gap-2 text-xs lg:text-sm text-muted-foreground">
                            <Clock className="w-3 h-3 lg:w-4 lg:h-4" />
                            <span className="font-mono truncate">{result.combo}</span>
                            <Badge variant="outline" className="text-[9px] lg:text-xs ml-auto">Queued</Badge>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div
                        key={result.id}
                        className={`rounded-lg border p-3 lg:p-4 animate-slide-in-right transition-all duration-300 ${getStatusBg(result.status)} ${result.status === "hit" ? "ring-1 ring-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.15)]" : ""}`}
                        data-testid={`result-${result.id}`}
                      >
                        <div className="flex items-center justify-between mb-1 lg:mb-2">
                          <div className="flex items-center gap-2">
                            <span className={getStatusColor(result.status)}>
                              {getStatusIcon(result.status)}
                            </span>
                            <Badge variant="outline" className="text-[10px] lg:text-xs">
                              {checkerInfo?.label || result.checker}
                            </Badge>
                            <Badge
                              className={`text-[10px] lg:text-xs ${statusBadgeClass(result.status)}`}
                              data-testid={`badge-status-${result.id}`}
                            >
                              {displayStatus(result.status)}
                            </Badge>
                          </div>
                          {result.status !== "checking" && result.status !== "skipped" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 lg:h-8 lg:w-8 p-0 transition-all duration-300"
                              onClick={() => copyResult(result)}
                              data-testid={`button-copy-${result.id}`}
                            >
                              <Copy className="w-3 h-3 lg:w-4 lg:h-4" />
                            </Button>
                          )}
                        </div>
                        <p className="text-xs lg:text-sm font-mono text-muted-foreground truncate" data-testid={`text-combo-${result.id}`}>
                          {result.combo}
                        </p>
                        {Object.keys(result.capture).length > 0 && result.status !== "checking" && result.status !== "skipped" && (
                          <div className="mt-2 lg:mt-3 grid grid-cols-2 gap-x-3 lg:gap-x-4 gap-y-0.5 lg:gap-y-1">
                            {Object.entries(result.capture).map(([key, val]) => (
                              <div key={key} className="flex items-center gap-1 text-[10px] lg:text-xs">
                                <span className="text-muted-foreground capitalize">{key}:</span>
                                <span className="font-medium truncate">{val}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <div ref={resultsEndRef} />
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
