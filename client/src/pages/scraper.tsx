import { useState, useCallback } from "react";
import { useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sheet, SheetContent, SheetTrigger, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import {
  Scan, Key, CreditCard, Copy, Loader2, Menu,
  Zap, Sparkles, Search, Target, Filter, ShoppingCart,
  GraduationCap, Settings, ShieldEllipsis, LogOut, User,
  LayoutDashboard, Shield, Tv, Gamepad2, BookOpen,
  CheckCircle2, XCircle, PlayCircle
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/lib/auth";
import { ThemeToggle } from "@/components/theme-toggle";
import { apiRequest } from "@/lib/queryClient";

interface ScrapeResult {
  results: string[];
  total: number;
  unique: number;
}

interface SkCheckResult {
  sk: string;
  status: "live" | "dead" | "error";
  message: string;
  elapsed?: number;
  currency?: string;
  country?: string;
  available?: string;
  pending?: string;
  account_id?: string;
  charges_enabled?: boolean;
  business_name?: string;
  business_url?: string;
}

export default function ScraperPage() {
  const [activeTab, setActiveTab] = useState("cc");
  const [chatId, setChatId] = useState("");
  const [limit, setLimit] = useState("100");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScrapeResult | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [autoCheckSk, setAutoCheckSk] = useState(true);
  const [skChecking, setSkChecking] = useState(false);
  const [skCheckProgress, setSkCheckProgress] = useState({ checked: 0, total: 0 });
  const [skCheckResults, setSkCheckResults] = useState<SkCheckResult[]>([]);
  const { toast } = useToast();
  const { user, isAdmin, logout } = useAuth();
  const [, navigate] = useLocation();

  const { data: checkerStatuses } = useQuery<Record<string, boolean>>({
    queryKey: ["/api/account-checkers/status"],
  });

  const { data: skCheckerStatus } = useQuery<{ enabled: boolean }>({
    queryKey: ["/api/tools/sk-checker-status"],
  });

  const checkSingleSk = useCallback(async (sk: string): Promise<SkCheckResult> => {
    try {
      const res = await apiRequest("POST", "/api/tools/check-sk", { sk });
      const data = await res.json();
      if (data.error) {
        return { sk, status: "error", message: data.error };
      }
      return data as SkCheckResult;
    } catch (err: any) {
      let msg = "Check failed";
      try { const p = JSON.parse(err.message.replace(/^\d+:\s*/, "")); msg = p.error || msg; } catch {}
      return { sk, status: "error", message: msg };
    }
  }, []);

  const handleCheckAllSks = useCallback(async (sks: string[]) => {
    if (sks.length === 0) return;
    setSkChecking(true);
    setSkCheckResults([]);
    setSkCheckProgress({ checked: 0, total: sks.length });

    const results: SkCheckResult[] = [];
    for (let i = 0; i < sks.length; i++) {
      const r = await checkSingleSk(sks[i]);
      results.push(r);
      setSkCheckResults([...results]);
      setSkCheckProgress({ checked: i + 1, total: sks.length });
    }

    const liveCount = results.filter(r => r.status === "live").length;
    const deadCount = results.filter(r => r.status === "dead").length;
    toast({ title: `SK Check Complete: ${liveCount} Live, ${deadCount} Dead` });
    setSkChecking(false);
  }, [checkSingleSk, toast]);

  const handleScrape = async () => {
    if (!chatId.trim()) {
      toast({ title: "Enter a group/channel ID or @username", variant: "destructive" });
      return;
    }

    const numLimit = Math.max(1, parseInt(limit) || 100);

    setLoading(true);
    setResult(null);
    try {
      const res = await apiRequest("POST", "/api/tools/scrape", {
        type: activeTab,
        chatId: chatId.trim(),
        limit: numLimit,
      });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
      } else {
        setResult(data);
        setSkCheckResults([]);
        toast({ title: `Found ${data.unique} unique ${activeTab === "cc" ? "cards" : "keys"}` });
        if (activeTab === "sk" && autoCheckSk && skCheckerStatus?.enabled !== false && data.results?.length > 0) {
          setTimeout(() => handleCheckAllSks(data.results), 500);
        }
      }
    } catch (err: any) {
      let msg = "Scrape failed";
      try { const p = JSON.parse(err.message.replace(/^\d+:\s*/, "")); msg = p.error || msg; } catch {}
      toast({ title: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const copyResults = () => {
    if (!result || result.results.length === 0) return;
    navigator.clipboard.writeText(result.results.join("\n"));
    toast({ title: `${result.results.length} items copied` });
  };

  const displayName = [user?.firstName, user?.lastName].filter(Boolean).join(" ") || user?.username || `ID: ${user?.userId}`;

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <header className="flex items-center justify-between gap-2 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
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
                    <p className="text-sm font-medium" data-testid="text-user-name">{displayName}</p>
                    <p className="text-xs text-muted-foreground" data-testid="text-user-role">
                      {isAdmin ? "Admin" : "User"} · {user?.userId}
                    </p>
                  </div>
                </div>

                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/"); }} data-testid="button-dashboard">
                  <LayoutDashboard className="w-4 h-4" />
                  Dashboard
                </Button>

                <div className="text-xs text-muted-foreground font-semibold mt-2 mb-1 px-1">Tools</div>

                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/checker"); }} data-testid="button-checker">
                  <Zap className="w-4 h-4" />
                  C-C Checker
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/generator"); }} data-testid="button-cc-generator">
                  <Sparkles className="w-4 h-4" />
                  CC Generator
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/finder"); }} data-testid="button-gateway-finder">
                  <Search className="w-4 h-4" />
                  Gateway Finder
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/autohitter"); }} data-testid="button-auto-hitter">
                  <Target className="w-4 h-4" />
                  Auto Hitter
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/filter"); }} data-testid="button-cc-filter">
                  <Filter className="w-4 h-4" />
                  CC Filter
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/shopify"); }} data-testid="button-auto-shopify">
                  <ShoppingCart className="w-4 h-4" />
                  Auto Shopify
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/skool"); }} data-testid="button-skool-gate">
                  <GraduationCap className="w-4 h-4" />
                  Skool Gate
                </Button>
                <Button variant="ghost" className="w-full justify-start gap-2 bg-primary/10" onClick={() => { setMenuOpen(false); navigate("/scraper"); }} data-testid="button-scraper">
                  <Scan className="w-4 h-4" />
                  SK/CC Scraper
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
                  <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/user-settings"); }} data-testid="button-settings">
                    <Settings className="w-4 h-4" />
                    Settings
                  </Button>
                  {isAdmin && (
                    <Button variant="outline" className="w-full justify-start gap-2 mb-2" onClick={() => { setMenuOpen(false); navigate("/admin"); }} data-testid="button-admin-panel">
                      <ShieldEllipsis className="w-4 h-4" />
                      Admin Panel
                    </Button>
                  )}
                  <Button variant="ghost" className="w-full justify-start gap-2 text-destructive hover:text-destructive" onClick={() => { setMenuOpen(false); logout(); }} data-testid="button-logout">
                    <LogOut className="w-4 h-4" />
                    Logout
                  </Button>
                </div>
              </div>
            </SheetContent>
          </Sheet>
          <div className="flex items-center gap-2">
            <Scan className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
            <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">SK/CC Scraper</h1>
          </div>
          {loading && (
            <Badge variant="secondary" className="text-xs" data-testid="badge-loading">
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
              Scraping...
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {isAdmin && (
            <Button variant="ghost" size="icon" onClick={() => navigate("/admin")} data-testid="button-admin-header" title="Admin Panel">
              <ShieldEllipsis className="w-4 h-4" />
            </Button>
          )}
          <ThemeToggle />
        </div>
      </header>

      <div className="flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-4xl mx-auto flex flex-col gap-4 lg:gap-6">
          <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v); setResult(null); setSkCheckResults([]); setSkChecking(false); }} className="w-full">
            <TabsList className="grid w-full grid-cols-2 animate-fade-in-up">
              <TabsTrigger value="cc" className="gap-2 transition-all duration-300" data-testid="tab-cc">
                <CreditCard className="w-4 h-4" />
                CC Scraper
              </TabsTrigger>
              <TabsTrigger value="sk" className="gap-2 transition-all duration-300" data-testid="tab-sk">
                <Key className="w-4 h-4" />
                SK Scraper
              </TabsTrigger>
            </TabsList>

            <TabsContent value="cc" className="mt-4">
              <Card className="animate-fade-in-up">
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    <span className="lg:text-xl">💳</span>
                    CC Scraper
                  </CardTitle>
                  <p className="text-xs lg:text-sm text-muted-foreground">
                    Scrape credit card details from Telegram groups/channels
                  </p>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3 flex flex-col gap-3 lg:gap-4">
                  <div className="flex flex-col gap-2">
                    <label className="text-xs lg:text-sm font-medium text-muted-foreground">Group/Channel ID or @username</label>
                    <Input
                      placeholder="@channel or -100xxxxxxxxx"
                      value={chatId}
                      onChange={e => setChatId(e.target.value)}
                      disabled={loading}
                      className="font-mono text-sm"
                      data-testid="input-chat-id"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label className="text-xs lg:text-sm font-medium text-muted-foreground">Message Limit (unlimited)</label>
                    <Input
                      type="number"
                      placeholder="100"
                      value={limit}
                      onChange={e => setLimit(e.target.value)}
                      disabled={loading}
                      min={1}
                      className="font-mono text-sm"
                      data-testid="input-limit"
                    />
                  </div>
                  <Button
                    onClick={handleScrape}
                    disabled={loading || !chatId.trim()}
                    className="w-full transition-all duration-300"
                    data-testid="button-scrape"
                  >
                    {loading ? (
                      <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2 animate-spin" />
                    ) : (
                      <Scan className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                    )}
                    {loading ? "Scraping..." : "Scrape CCs"}
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="sk" className="mt-4">
              <Card className="animate-fade-in-up">
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    <span className="lg:text-xl">🔑</span>
                    SK Scraper
                  </CardTitle>
                  <p className="text-xs lg:text-sm text-muted-foreground">
                    Scrape Stripe secret keys from Telegram groups/channels
                  </p>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3 flex flex-col gap-3 lg:gap-4">
                  <div className="flex flex-col gap-2">
                    <label className="text-xs lg:text-sm font-medium text-muted-foreground">Group/Channel ID or @username</label>
                    <Input
                      placeholder="@channel or -100xxxxxxxxx"
                      value={chatId}
                      onChange={e => setChatId(e.target.value)}
                      disabled={loading}
                      className="font-mono text-sm"
                      data-testid="input-chat-id-sk"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label className="text-xs lg:text-sm font-medium text-muted-foreground">Message Limit (unlimited)</label>
                    <Input
                      type="number"
                      placeholder="100"
                      value={limit}
                      onChange={e => setLimit(e.target.value)}
                      disabled={loading}
                      min={1}
                      className="font-mono text-sm"
                      data-testid="input-limit-sk"
                    />
                  </div>
                  {skCheckerStatus?.enabled !== false && (
                    <div className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border">
                      <div className="flex flex-col">
                        <span className="text-xs lg:text-sm font-medium">Auto-Check SKs</span>
                        <span className="text-[10px] lg:text-xs text-muted-foreground">Verify scraped keys via Stripe API</span>
                      </div>
                      <Switch
                        checked={autoCheckSk}
                        onCheckedChange={setAutoCheckSk}
                        disabled={loading || skChecking}
                      />
                    </div>
                  )}
                  <Button
                    onClick={handleScrape}
                    disabled={loading || skChecking || !chatId.trim()}
                    className="w-full transition-all duration-300"
                    data-testid="button-scrape-sk"
                  >
                    {loading ? (
                      <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2 animate-spin" />
                    ) : (
                      <Scan className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                    )}
                    {loading ? "Scraping..." : "Scrape SKs"}
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {result && (
            <>
              <div className="grid grid-cols-2 gap-3 lg:gap-4">
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "0ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-primary" data-testid="text-total-scanned">{result.total}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Messages Scanned</span>
                  </div>
                </Card>
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "50ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-emerald-400" data-testid="text-unique-found">{result.unique}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Unique Items</span>
                  </div>
                </Card>
              </div>

              <Card className="animate-fade-in-up" style={{ animationDelay: "100ms" }}>
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between gap-2">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    Results
                    <Badge variant="secondary" className="text-xs lg:text-sm">{result.results.length}</Badge>
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    {activeTab === "sk" && result.results.length > 0 && skCheckerStatus?.enabled !== false && !skChecking && skCheckResults.length === 0 && (
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => handleCheckAllSks(result.results)}
                        className="transition-all duration-300"
                      >
                        <PlayCircle className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                        Check All
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={copyResults}
                      disabled={result.results.length === 0}
                      className="transition-all duration-300"
                      data-testid="button-copy-all"
                    >
                      <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                      Copy All
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3">
                  <Textarea
                    readOnly
                    value={result.results.join("\n")}
                    className="min-h-[200px] lg:min-h-[300px] font-mono text-xs lg:text-sm resize-none"
                    placeholder="No results found..."
                    data-testid="textarea-results"
                  />
                </CardContent>
              </Card>

              {activeTab === "sk" && (skChecking || skCheckResults.length > 0) && (
                <Card className="animate-fade-in-up" style={{ animationDelay: "150ms" }}>
                  <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                    <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                      <Key className="w-4 h-4" />
                      SK Check Results
                      {skChecking && (
                        <Badge variant="secondary" className="text-xs">
                          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          {skCheckProgress.checked}/{skCheckProgress.total}
                        </Badge>
                      )}
                      {!skChecking && skCheckResults.length > 0 && (
                        <>
                          <Badge className="text-xs bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                            {skCheckResults.filter(r => r.status === "live").length} Live
                          </Badge>
                          <Badge className="text-xs bg-red-500/20 text-red-400 border-red-500/30">
                            {skCheckResults.filter(r => r.status === "dead").length} Dead
                          </Badge>
                        </>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3">
                    <div className="flex flex-col gap-2 max-h-[400px] overflow-y-auto">
                      {skCheckResults.map((r, i) => (
                        <div
                          key={i}
                          className={`p-3 rounded-lg border text-xs lg:text-sm font-mono transition-all duration-300 animate-fade-in-up ${
                            r.status === "live"
                              ? "bg-emerald-500/10 border-emerald-500/30"
                              : r.status === "dead"
                              ? "bg-red-500/5 border-red-500/20"
                              : "bg-yellow-500/5 border-yellow-500/20"
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            {r.status === "live" ? (
                              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                            ) : r.status === "dead" ? (
                              <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                            ) : (
                              <XCircle className="w-4 h-4 text-yellow-400 shrink-0" />
                            )}
                            <span className={`font-semibold ${
                              r.status === "live" ? "text-emerald-400" : r.status === "dead" ? "text-red-400" : "text-yellow-400"
                            }`}>
                              {r.status.toUpperCase()}
                            </span>
                            <span className="text-muted-foreground">
                              {r.message}
                            </span>
                            {r.elapsed && (
                              <span className="text-muted-foreground ml-auto">
                                {r.elapsed}s
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] lg:text-xs text-muted-foreground truncate">
                            {r.sk.substring(0, 20)}...{r.sk.substring(r.sk.length - 6)}
                          </div>
                          {r.status === "live" && (
                            <div className="mt-2 grid grid-cols-2 gap-1 text-[10px] lg:text-xs">
                              <span>Balance: {r.available}</span>
                              <span>Pending: {r.pending}</span>
                              <span>Currency: {r.currency} ({r.country})</span>
                              <span>Charges: {r.charges_enabled ? "Yes" : "No"}</span>
                              {r.business_name && r.business_name !== "N/A" && (
                                <span className="col-span-2">Business: {r.business_name}</span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                      {skChecking && skCheckProgress.checked < skCheckProgress.total && (
                        <div className="flex items-center justify-center p-3 text-muted-foreground text-xs gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Checking {skCheckProgress.checked + 1} of {skCheckProgress.total}...
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
