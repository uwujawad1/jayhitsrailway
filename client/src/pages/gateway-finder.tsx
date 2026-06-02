import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Search, ArrowLeft, Loader2, Globe, ExternalLink, Copy, Key,
  Shield, ShieldCheck, ShieldAlert, Lock, Scan, CreditCard
} from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { PageTransition } from "@/components/page-transition";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";

interface SiteResult {
  url: string;
  domain: string;
  evidence: string;
  keys?: string[];
  rzp_link?: string;
}

interface FinderResult {
  gateway: string;
  searched: number;
  found: SiteResult[];
  count: number;
  elapsed: number;
}

interface SiteCheckResult {
  url: string;
  status_code: number;
  cloudflare: { detected: boolean };
  captcha: { detected: boolean; types?: string[] };
  graphql: { detected: boolean; endpoints?: string[] };
  cms: { detected: string };
  payments: { gateways: string[]; count: number; evidence?: string[] };
  checkout: { features: Record<string, boolean>; score: number };
  security: { score: number };
  ssl: { valid: boolean; issuer?: string; subject?: string; expires?: string };
  waf: { detected: string[] };
  elapsed: number;
}

const FALLBACK_GATEWAYS = [
  "stripe", "braintree", "razorpay", "shopify", "paypal", "square",
  "adyen", "authorize.net", "worldpay", "cybersource", "sagepay",
  "klarna", "mollie", "payu", "paystack", "elavon", "heartland",
];

const PROGRESS_STEPS = [
  "Generating search queries...",
  "Searching Google, Bing, DuckDuckGo...",
  "Searching Brave, Startpage...",
  "Filtering candidate URLs...",
  "Verifying gateway on sites...",
  "Extracting keys & data...",
  "Almost done...",
];

export default function GatewayFinderPage() {
  const [gateway, setGateway] = useState("stripe");
  const [count, setCount] = useState("10");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [progressStep, setProgressStep] = useState(0);
  const [result, setResult] = useState<FinderResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"finder" | "checker">("finder");
  const [siteUrl, setSiteUrl] = useState("");
  const [checkingUrl, setCheckingUrl] = useState(false);
  const [siteResult, setSiteResult] = useState<SiteCheckResult | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const { toast } = useToast();
  const [, navigate] = useLocation();

  const { data: supportedGateways } = useQuery<string[]>({
    queryKey: ["/api/tools/findsite/gateways"],
  });
  const gateways = supportedGateways || FALLBACK_GATEWAYS;

  useEffect(() => {
    if (loading) {
      setElapsed(0);
      setProgressStep(0);
      timerRef.current = setInterval(() => {
        setElapsed(prev => prev + 1);
        setProgressStep(prev => {
          if (prev < PROGRESS_STEPS.length - 1) return prev + 1;
          return prev;
        });
      }, 8000);
      const fastTimer = setInterval(() => setElapsed(prev => prev + 1), 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
        clearInterval(fastTimer);
      };
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  }, [loading]);

  const handleSearch = async () => {
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await apiRequest("POST", "/api/tools/findsite", {
        gateway,
        count: parseInt(count) || 10,
      });
      const data: FinderResult = await res.json();
      setResult(data);
      if (data.count === 0) {
        toast({ title: `No ${gateway} sites found`, variant: "destructive" });
      } else {
        toast({ title: `Found ${data.count} ${gateway} sites in ${data.elapsed}s` });
      }
    } catch (err: any) {
      const msg = err?.message || "Search failed";
      setError(msg);
      toast({ title: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const handleSiteCheck = async () => {
    const url = siteUrl.trim();
    if (!url) return;

    setCheckingUrl(true);
    setSiteResult(null);
    setSiteError(null);

    try {
      const res = await apiRequest("POST", "/api/tools/site-check", { url });
      const data = await res.json();
      setSiteResult(data);
      const gwCount = data.payments?.count || 0;
      toast({ title: `Analysis complete`, description: `${gwCount} gateway(s) found in ${data.elapsed}s` });
    } catch (err: any) {
      let msg = "Analysis failed";
      try { const parsed = JSON.parse(err.message.replace(/^\d+:\s*/, "")); msg = parsed.error || msg; } catch {}
      setSiteError(msg);
      toast({ title: "Analysis failed", description: msg, variant: "destructive" });
    } finally {
      setCheckingUrl(false);
    }
  };

  const copyAllSites = () => {
    if (!result?.found?.length) return;
    const text = result.found.map((s, i) => {
      let line = `${i + 1}. ${s.url}`;
      if (s.keys?.length) line += `\n   Keys: ${s.keys.join(", ")}`;
      return line;
    }).join("\n");
    navigator.clipboard.writeText(text);
    toast({ title: `${result.found.length} sites copied` });
  };

  const copyKeys = () => {
    if (!result?.found) return;
    const allKeys = result.found.flatMap(s => s.keys || []);
    if (allKeys.length === 0) {
      toast({ title: "No keys found", variant: "destructive" });
      return;
    }
    navigator.clipboard.writeText(allKeys.join("\n"));
    toast({ title: `${allKeys.length} keys copied` });
  };

  const allKeys = result?.found?.flatMap(s => s.keys || []) || [];

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <div className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back">
          <ArrowLeft className="w-4 h-4 lg:w-5 lg:h-5" />
        </Button>
        <Search className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Gateway Tools</h1>
        {loading && (
          <Badge variant="secondary" className="text-xs lg:text-sm">
            <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1 animate-spin" />
            {elapsed}s
          </Badge>
        )}
      </div>

      <PageTransition className="flex-1 overflow-x-hidden p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <div className="flex gap-2 lg:gap-3">
            <Button
              variant={activeTab === "finder" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveTab("finder")}
              className="flex-1 transition-all duration-300"
              data-testid="tab-finder"
            >
              <Search className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1.5" />
              <span className="lg:text-sm">Gateway Finder</span>
            </Button>
            <Button
              variant={activeTab === "checker" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveTab("checker")}
              className="flex-1 transition-all duration-300"
              data-testid="tab-site-checker"
            >
              <Scan className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1.5" />
              <span className="lg:text-sm">Site Checker</span>
            </Button>
          </div>

          {activeTab === "checker" && (
            <>
              <Card className="animate-fade-in-up">
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    <Scan className="w-4 h-4 lg:w-5 lg:h-5 text-primary transition-transform duration-300 hover:scale-110" />
                    Analyze Website
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
                  <p className="text-[11px] lg:text-sm text-muted-foreground">
                    Check any website for payment gateways, security, SSL, captcha, and more.
                  </p>
                  <div className="flex gap-2 lg:gap-3">
                    <Input
                      placeholder="example.com or https://shop.example.com"
                      value={siteUrl}
                      onChange={e => setSiteUrl(e.target.value)}
                      className="flex-1 text-xs lg:text-sm"
                      disabled={checkingUrl}
                      onKeyDown={e => e.key === "Enter" && handleSiteCheck()}
                      data-testid="input-site-url"
                    />
                    <Button
                      size="sm"
                      onClick={handleSiteCheck}
                      disabled={!siteUrl.trim() || checkingUrl}
                      className="transition-all duration-300"
                      data-testid="button-check-site"
                    >
                      {checkingUrl ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 lg:w-4 lg:h-4 animate-spin mr-1" />
                          <span className="lg:text-sm">Analyzing...</span>
                        </>
                      ) : (
                        <>
                          <Scan className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                          <span className="lg:text-sm">Check</span>
                        </>
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {siteError && !checkingUrl && (
                <Card className="border-red-500/30 animate-fade-in-up">
                  <CardContent className="p-4 lg:p-6">
                    <p className="text-sm lg:text-base text-red-400" data-testid="text-site-error">{siteError}</p>
                  </CardContent>
                </Card>
              )}

              {siteResult && (
                <Card className="animate-fade-in-up">
                  <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                    <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                      <Globe className="w-4 h-4 lg:w-5 lg:h-5" />
                      Results
                      <span className="text-xs lg:text-sm text-muted-foreground font-normal">({siteResult.elapsed}s)</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
                    <div className="text-xs lg:text-sm break-all text-muted-foreground" data-testid="text-analyzed-url">
                      {siteResult.url}
                    </div>

                    <div className="grid grid-cols-2 gap-2 lg:gap-4">
                      <div className="rounded-md border p-2.5 lg:p-4 bg-muted/30 transition-all duration-300 hover:scale-[1.02] hover:shadow-md">
                        <div className="flex items-center gap-1.5 lg:gap-2 mb-1 lg:mb-2">
                          <CreditCard className="w-3.5 h-3.5 lg:w-5 lg:h-5 text-primary transition-transform duration-300 hover:scale-110" />
                          <span className="text-[11px] lg:text-sm font-medium">Gateways</span>
                        </div>
                        {siteResult.payments.count > 0 ? (
                          <div className="flex flex-wrap gap-1 lg:gap-1.5">
                            {siteResult.payments.gateways.map((gw, i) => (
                              <Badge key={i} variant="secondary" className="text-[10px] lg:text-xs" data-testid={`badge-gateway-${i}`}>{gw}</Badge>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[10px] lg:text-xs text-muted-foreground">None Detected</p>
                        )}
                      </div>

                      <div className="rounded-md border p-2.5 lg:p-4 bg-muted/30 transition-all duration-300 hover:scale-[1.02] hover:shadow-md">
                        <div className="flex items-center gap-1.5 lg:gap-2 mb-1 lg:mb-2">
                          <Shield className="w-3.5 h-3.5 lg:w-5 lg:h-5 text-blue-400 transition-transform duration-300 hover:scale-110" />
                          <span className="text-[11px] lg:text-sm font-medium">Cloudflare</span>
                        </div>
                        <Badge variant={siteResult.cloudflare.detected ? "destructive" : "secondary"} className="text-[10px] lg:text-xs">
                          {siteResult.cloudflare.detected ? "Protected" : "Not Protected"}
                        </Badge>
                      </div>

                      <div className="rounded-md border p-2.5 lg:p-4 bg-muted/30 transition-all duration-300 hover:scale-[1.02] hover:shadow-md">
                        <div className="flex items-center gap-1.5 lg:gap-2 mb-1 lg:mb-2">
                          <ShieldAlert className="w-3.5 h-3.5 lg:w-5 lg:h-5 text-amber-400 transition-transform duration-300 hover:scale-110" />
                          <span className="text-[11px] lg:text-sm font-medium">Captcha</span>
                        </div>
                        {siteResult.captcha.detected ? (
                          <div className="flex flex-wrap gap-1 lg:gap-1.5">
                            {(siteResult.captcha.types || ["Detected"]).map((t, i) => (
                              <Badge key={i} variant="destructive" className="text-[10px] lg:text-xs">{t}</Badge>
                            ))}
                          </div>
                        ) : (
                          <Badge variant="secondary" className="text-[10px] lg:text-xs">Not Protected</Badge>
                        )}
                      </div>

                      <div className="rounded-md border p-2.5 lg:p-4 bg-muted/30 transition-all duration-300 hover:scale-[1.02] hover:shadow-md">
                        <div className="flex items-center gap-1.5 lg:gap-2 mb-1 lg:mb-2">
                          <Lock className="w-3.5 h-3.5 lg:w-5 lg:h-5 text-emerald-400 transition-transform duration-300 hover:scale-110" />
                          <span className="text-[11px] lg:text-sm font-medium">SSL</span>
                        </div>
                        <Badge variant={siteResult.ssl.valid ? "secondary" : "destructive"} className="text-[10px] lg:text-xs">
                          {siteResult.ssl.valid ? "Valid" : "Invalid"}
                        </Badge>
                      </div>
                    </div>

                    <div className="rounded-md border p-2.5 lg:p-4 bg-muted/30">
                      <p className="text-[11px] lg:text-sm font-medium mb-1.5 lg:mb-2.5">Details</p>
                      <div className="grid grid-cols-2 gap-x-4 lg:gap-x-6 gap-y-1 lg:gap-y-2 text-[11px] lg:text-sm">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">CMS</span>
                          <span data-testid="text-cms">{siteResult.cms.detected || "Unknown"}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Checkout</span>
                          <span data-testid="text-checkout">
                            {siteResult.checkout.score > 60 ? "Available" : siteResult.checkout.score > 30 ? "Partial" : "Not Found"}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">GraphQL</span>
                          <span data-testid="text-graphql">{siteResult.graphql.detected ? "Available" : "Not Found"}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Security</span>
                          <span data-testid="text-security">{siteResult.security.score}%</span>
                        </div>
                        {siteResult.waf.detected.length > 0 && (
                          <div className="flex justify-between col-span-2">
                            <span className="text-muted-foreground">WAF</span>
                            <span>{siteResult.waf.detected.join(", ")}</span>
                          </div>
                        )}
                        {siteResult.ssl.issuer && (
                          <div className="flex justify-between col-span-2">
                            <span className="text-muted-foreground">SSL Issuer</span>
                            <span className="text-right truncate max-w-[200px] lg:max-w-[400px]" data-testid="text-ssl-issuer">{siteResult.ssl.issuer}</span>
                          </div>
                        )}
                        {siteResult.ssl.expires && (
                          <div className="flex justify-between col-span-2">
                            <span className="text-muted-foreground">SSL Expires</span>
                            <span data-testid="text-ssl-expires">{siteResult.ssl.expires}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}

          {activeTab === "finder" && (
          <>
          <Card className="animate-fade-in-up">
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg">Find Sites Using a Payment Gateway</CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
              <div>
                <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">Gateway</label>
                <Select value={gateway} onValueChange={setGateway} disabled={loading}>
                  <SelectTrigger data-testid="select-gateway">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {gateways.map(g => (
                      <SelectItem key={g} value={g}>{g.charAt(0).toUpperCase() + g.slice(1)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">Max results (1-25)</label>
                <Input
                  type="number"
                  min={1}
                  max={25}
                  value={count}
                  onChange={e => setCount(e.target.value)}
                  disabled={loading}
                  data-testid="input-count"
                />
              </div>
              <Button onClick={handleSearch} disabled={loading} className="transition-all duration-300" data-testid="button-search">
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2 animate-spin" />
                    <span className="lg:text-sm">Searching...</span>
                  </>
                ) : (
                  <>
                    <Search className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                    <span className="lg:text-sm">Find Sites</span>
                  </>
                )}
              </Button>
              {loading && (
                <div className="rounded-md border bg-muted/30 p-3 lg:p-5 text-center">
                  <Loader2 className="w-5 h-5 lg:w-6 lg:h-6 animate-spin mx-auto mb-2 text-primary" />
                  <p className="text-xs lg:text-sm font-medium" data-testid="text-progress">{PROGRESS_STEPS[progressStep]}</p>
                  <p className="text-[10px] lg:text-xs text-muted-foreground mt-1">
                    This typically takes 30-90 seconds. Searching multiple engines and verifying gateways...
                  </p>
                  <div className="w-full bg-muted rounded-full h-1.5 lg:h-2 mt-2">
                    <div
                      className="bg-primary h-1.5 lg:h-2 rounded-full transition-all duration-1000"
                      style={{ width: `${Math.min((elapsed / 70) * 100, 95)}%` }}
                    />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {error && !loading && (
            <Card className="border-red-500/30 animate-fade-in-up">
              <CardContent className="p-4 lg:p-6">
                <p className="text-sm lg:text-base text-red-400">{error}</p>
              </CardContent>
            </Card>
          )}

          {result && (
            <>
              <Card className="animate-fade-in-up">
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between">
                  <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                    <Globe className="w-4 h-4 lg:w-5 lg:h-5" />
                    Results
                    <Badge variant="secondary" className="text-xs lg:text-sm">{result.count} found</Badge>
                    <span className="text-xs lg:text-sm text-muted-foreground font-normal">
                      ({result.searched} searched, {result.elapsed}s)
                    </span>
                  </CardTitle>
                  <div className="flex gap-1">
                    {result.count > 0 && (
                      <Button size="icon" variant="ghost" onClick={copyAllSites} className="transition-all duration-300" data-testid="button-copy-sites">
                        <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                  {result.count === 0 ? (
                    <div className="text-center py-6 lg:py-10 text-muted-foreground">
                      <Search className="w-6 h-6 lg:w-8 lg:h-8 mx-auto mb-2 opacity-30" />
                      <p className="text-sm lg:text-base">No sites found with {result.gateway} gateway.</p>
                      <p className="text-xs lg:text-sm mt-1">Try a different gateway or increase max results.</p>
                    </div>
                  ) : (
                    <ScrollArea className="max-h-[400px] lg:max-h-[500px]">
                      <div className="flex flex-col gap-2 lg:gap-3">
                        {result.found.map((site, i) => (
                          <div key={i} className="rounded-md border p-3 lg:p-4 bg-muted/30 transition-all duration-300 hover:bg-muted/50" data-testid={`card-site-${i}`}>
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1 min-w-0">
                                <p className="text-sm lg:text-base font-medium break-all" data-testid={`text-domain-${i}`}>{site.domain}</p>
                                <p className="text-xs lg:text-sm text-muted-foreground break-all mt-0.5">{site.url}</p>
                                <Badge variant="outline" className="text-[10px] lg:text-xs mt-1">{site.evidence}</Badge>
                              </div>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="shrink-0 transition-all duration-300"
                                onClick={() => window.open(site.url, "_blank")}
                                data-testid={`button-open-site-${i}`}
                              >
                                <ExternalLink className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                              </Button>
                            </div>
                            {site.keys && site.keys.length > 0 && (
                              <div className="mt-2 flex flex-col gap-1">
                                {site.keys.map((key, ki) => (
                                  <div key={ki} className="flex items-center gap-1.5 text-xs lg:text-sm">
                                    <Key className="w-3 h-3 lg:w-4 lg:h-4 text-amber-500 shrink-0" />
                                    <code className="font-mono text-[11px] lg:text-xs break-all text-amber-500" data-testid={`text-key-${i}-${ki}`}>
                                      {key}
                                    </code>
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="h-5 w-5 lg:h-6 lg:w-6 shrink-0 transition-all duration-300"
                                      onClick={() => {
                                        navigator.clipboard.writeText(key);
                                        toast({ title: "Key copied" });
                                      }}
                                      data-testid={`button-copy-key-${i}-${ki}`}
                                    >
                                      <Copy className="w-2.5 h-2.5 lg:w-3 lg:h-3" />
                                    </Button>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  )}
                </CardContent>
              </Card>

              {allKeys.length > 0 && (
                <Card className="animate-fade-in-up">
                  <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between">
                    <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                      <Key className="w-4 h-4 lg:w-5 lg:h-5 text-amber-500 transition-transform duration-300 hover:scale-110" />
                      All Keys
                      <Badge variant="secondary" className="text-xs lg:text-sm">{allKeys.length}</Badge>
                    </CardTitle>
                    <Button size="sm" variant="ghost" onClick={copyKeys} className="transition-all duration-300" data-testid="button-copy-all-keys">
                      <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                      <span className="lg:text-sm">Copy All</span>
                    </Button>
                  </CardHeader>
                  <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
                    <ScrollArea className="max-h-[150px] lg:max-h-[200px]">
                      <div className="flex flex-col gap-1 lg:gap-1.5">
                        {allKeys.map((key, i) => (
                          <code key={i} className="text-xs lg:text-sm font-mono text-amber-500 break-all block" data-testid={`text-all-key-${i}`}>
                            {key}
                          </code>
                        ))}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              )}
            </>
          )}
          </>
          )}
        </div>
      </PageTransition>
    </div>
  );
}
