import { useState, useRef, useEffect } from "react";
import { useLocation } from "wouter";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Target, Loader2, Copy, ArrowLeft,
  ShieldCheck, XCircle, AlertTriangle, CreditCard, Sparkles, Clock, ChevronDown, ChevronUp,
  Save, Trash2, Star, Zap, Globe, DollarSign, Lock, LockOpen, Store, CheckCircle2, Hash
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, apiUrl } from "@/lib/queryClient";

interface HitResult {
  id: string;
  card: string;
  status: string;
  message: string;
  elapsed: number;
  timestamp: number;
}

interface HistorySession {
  id: string;
  url: string;
  merchant: string;
  amount: string;
  totalCards: number;
  charged: number;
  threeDs: number;
  declined: number;
  errors: number;
  chargedCards: { card: string; message: string }[];
  timestamp: number;
  bin?: string;
}

function is3dsBypassed(message: string): boolean {
  if (!/3ds bypassed/i.test(message)) return false;
  const lower = message.toLowerCase();
  if (lower.includes("authentication failed") || lower.includes("authentication_failure") || lower.includes("authentication required")) return false;
  return true;
}

function is3dsFailed(status: string, message: string): boolean {
  if (is3dsBypassed(message)) return false;
  if (status === "live") return true;
  if (/3ds authentication/i.test(message)) return true;
  if (/authentication.*(failed|failure|required)/i.test(message)) return true;
  return false;
}

function getStatusColor(status: string) {
  switch (status) {
    case "charged": return "text-emerald-400";
    case "live": return "text-amber-400";
    case "live_declined": return "text-red-400";
    case "error": return "text-yellow-400";
    default: return "text-red-400";
  }
}

function getStatusLabel(status: string) {
  switch (status) {
    case "charged": return "CHARGED";
    case "live": return "3DS REQUIRED";
    case "live_declined": return "DECLINED";
    case "error": return "ERROR";
    default: return status.toUpperCase();
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case "charged": return <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
    case "live": return <Lock className="w-3.5 h-3.5 text-amber-400 shrink-0" />;
    case "live_declined": return <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />;
    default: return <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 shrink-0" />;
  }
}

const DECLINE_MAP: Record<string, string> = {
  "generic_decline": "Generic Decline",
  "card_declined": "Card Declined",
  "insufficient_funds": "Insufficient Funds",
  "incorrect_cvc": "Incorrect CVC",
  "invalid_cvc": "Invalid CVC",
  "expired_card": "Expired Card",
  "incorrect_zip": "Incorrect ZIP",
  "do_not_honor": "Do Not Honor",
  "lost_card": "Lost Card",
  "stolen_card": "Stolen Card",
  "pickup_card": "Pickup Card",
  "restricted_card": "Restricted Card",
  "security_violation": "Security Violation",
  "card_velocity_exceeded": "Velocity Exceeded",
  "withdrawal_count_limit_exceeded": "Withdrawal Limit",
  "try_again_later": "Try Again Later",
  "not_permitted": "Not Permitted",
  "processing_error": "Processing Error",
  "fraudulent": "Flagged Fraudulent",
  "transaction_not_allowed": "Not Allowed",
  "payment method failed": "Payment Failed",
};

function formatDeclineReason(message: string, wasBypassed: boolean): string {
  const clean = message
    .replace(/\(3DS Bypassed\)/gi, "")
    .replace(/\(3DS Cancelled\)/gi, "")
    .trim();

  const lower = clean.toLowerCase();

  if (lower.includes("charged")) return "Charged Successfully";
  if (lower.includes("authorized")) return "Authorized";
  if (lower.includes("processing")) return "Processing";
  if (lower.includes("setup succeeded")) return "Setup Succeeded";

  if (lower === "3ds authentication required" || lower === "3ds authentication failed") {
    return "3DS Could Not Be Bypassed";
  }

  for (const [key, label] of Object.entries(DECLINE_MAP)) {
    if (lower.includes(key)) return label;
  }

  return clean.length > 50 ? clean.slice(0, 50) + "..." : clean;
}

function ResultRow({ r }: { r: HitResult }) {
  const bypassed = is3dsBypassed(r.message);
  const threeDsFailed = is3dsFailed(r.status, r.message);
  const reason = formatDeclineReason(r.message, bypassed);

  const boxStyle = r.status === "charged"
    ? "border-emerald-500/30 bg-emerald-500/5"
    : bypassed
      ? "border-emerald-500/20 bg-emerald-500/5"
      : threeDsFailed
        ? "border-amber-500/20 bg-amber-500/5"
        : r.status === "error"
          ? "border-yellow-500/20 bg-yellow-500/5"
          : "border-red-500/20 bg-red-500/5";

  const reasonColor = r.status === "charged"
    ? "text-emerald-400"
    : bypassed
      ? "text-red-400"
      : threeDsFailed
        ? "text-amber-400"
        : r.status === "error"
          ? "text-yellow-400"
          : "text-red-400";

  return (
    <div className={`rounded-lg border mx-2 my-1.5 px-3.5 py-2.5 ${boxStyle}`} data-testid={`row-result-${r.id}`}>
      <div className="flex items-center gap-2">
        {getStatusIcon(r.status)}
        <code className="text-[11px] font-mono text-foreground/90">{r.card}</code>
        <div className="flex-1" />
        {bypassed && (
          <Badge className="text-[9px] px-1.5 py-0 h-4 bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20 shrink-0" data-testid={`tag-3ds-bypassed-${r.id}`}>
            <LockOpen className="w-2.5 h-2.5 mr-0.5" />
            3DS BYPASSED
          </Badge>
        )}
        {threeDsFailed && (
          <Badge className="text-[9px] px-1.5 py-0 h-4 bg-amber-500/15 text-amber-400 border-amber-500/30 hover:bg-amber-500/20 shrink-0" data-testid={`tag-3ds-failed-${r.id}`}>
            <Lock className="w-2.5 h-2.5 mr-0.5" />
            3DS BLOCKED
          </Badge>
        )}
        <span className="text-[10px] text-muted-foreground shrink-0">{r.elapsed}s</span>
      </div>
      <div className="mt-1.5 pl-[22px]">
        <span className={`text-[11px] font-semibold ${reasonColor}`}>{reason}</span>
      </div>
    </div>
  );
}

const ZERO_DECIMAL_CURRENCIES = ["BIF","CLP","DJF","GNF","JPY","KMF","KRW","MGA","PYG","RWF","UGX","VND","VUV","XAF","XOF","XPF"];

function formatAmount(rawAmount: number | string | null | undefined, currency: string): string | undefined {
  if (rawAmount == null || rawAmount === "") return undefined;
  const num = Number(rawAmount);
  if (isNaN(num)) return undefined;
  const cur = (currency || "").toUpperCase();
  return ZERO_DECIMAL_CURRENCIES.includes(cur) ? String(num) : (num / 100).toFixed(2);
}

const FAKE_RESPONSES: { status: string; message: string }[] = [
  { status: "live_declined", message: "generic_decline" },
  { status: "live_declined", message: "generic_decline" },
  { status: "live_declined", message: "insufficient_funds" },
  { status: "live_declined", message: "card_declined" },
  { status: "live_declined", message: "do_not_honor" },
  { status: "live_declined", message: "lost_card" },
  { status: "live_declined", message: "stolen_card" },
  { status: "live_declined", message: "incorrect_cvc" },
  { status: "live_declined", message: "expired_card" },
  { status: "live", message: "3DS Authentication Required" },
  { status: "live", message: "3DS Authentication Required" },
  { status: "live_declined", message: "generic_decline (3DS Bypassed)" },
  { status: "live_declined", message: "insufficient_funds (3DS Bypassed)" },
  { status: "live_declined", message: "do_not_honor (3DS Bypassed)" },
  { status: "live_declined", message: "card_declined (3DS Bypassed)" },
];

export default function FakeLogsPage() {
  const [mode, setMode] = useState<string>("cards");
  const [checkoutUrl, setCheckoutUrl] = useState("");
  const [cardInput, setCardInput] = useState("");
  const [binInput, setBinInput] = useState("");
  const [binCount, setBinCount] = useState("10");
  const [results, setResults] = useState<HitResult[]>([]);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState(0);
  const [merchantInfo, setMerchantInfo] = useState<{
    merchant?: string;
    amount?: string;
    rawAmount?: number;
    currency?: string;
    pk?: string;
    billing_required?: boolean;
    chargeSuccess?: boolean;
    chargedCard?: string;
    chargedMessage?: string;
    totalAttempts?: number;
  } | null>(null);
  const abortRef = useRef(false);
  const checkoutCacheRef = useRef<any>(null);
  const { toast } = useToast();
  const [, navigate] = useLocation();
  const [history, setHistory] = useState<HistorySession[]>([]);
  const [expandedHistory, setExpandedHistory] = useState<string | null>(null);
  const currentBinRef = useRef<string>("");
  const [savedBins, setSavedBins] = useState<{ bin: string; label: string }[]>([]);
  const [saveBinLabel, setSaveBinLabel] = useState("");
  const [showSaveBin, setShowSaveBin] = useState(false);

  useEffect(() => {
    fetch(apiUrl("/api/tools/saved-bins"), { credentials: "include" })
      .then(r => r.json())
      .then(d => setSavedBins(d.bins || []))
      .catch(() => {});
  }, []);

  const handleSaveBin = async () => {
    const bin = binInput.trim();
    if (!bin || bin.length < 6) {
      toast({ title: "Enter a valid BIN first (at least 6 digits)", variant: "destructive" });
      return;
    }
    try {
      const res = await fetch(apiUrl("/api/tools/saved-bins"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ bin, label: saveBinLabel || bin.slice(0, 6) }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        toast({ title: data.error || "Failed to save BIN", variant: "destructive" });
      } else {
        setSavedBins(data.bins || []);
        setSaveBinLabel("");
        setShowSaveBin(false);
        toast({ title: "BIN saved" });
      }
    } catch (err: any) {
      toast({ title: err.message || "Failed to save BIN", variant: "destructive" });
    }
  };

  const handleDeleteBin = async (bin: string) => {
    try {
      const res = await fetch(apiUrl("/api/tools/saved-bins"), {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ bin }),
      });
      const data = await res.json();
      if (res.ok) {
        setSavedBins(data.bins || []);
        toast({ title: "BIN removed" });
      }
    } catch {}
  };

  const handleUseSavedBin = (bin: string) => {
    setBinInput(bin);
    setMode("bin");
  };

  const validateUrl = (url: string) => {
    return url.includes("checkout.stripe.com") || url.includes("cs_live_") || url.includes("cs_test_") || (url.includes("stripe.com") && url.includes("pay"));
  };

  const generateCards = async (bin: string, amount: number): Promise<string[]> => {
    try {
      const res = await apiRequest("POST", "/api/tools/generate", { bin, amount, month: "xx", year: "xx", cvv: "xxx" });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
        return [];
      }
      return data.cards || [];
    } catch (err: any) {
      toast({ title: err.message || "Failed to generate cards", variant: "destructive" });
      return [];
    }
  };

  const processCards = async (cards: string[], url: string) => {
    setRunning(true);
    abortRef.current = false;
    checkoutCacheRef.current = null;
    setTotal(cards.length);
    setCurrent(0);
    setResults([]);
    setMerchantInfo(null);

    const allResults: HitResult[] = [];

    try {
      const fetchRes = await fetch(apiUrl("/api/admin/fake-logs/fetch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ checkoutUrl: url }),
      });
      const fetchData = await fetchRes.json();

      if (!fetchRes.ok || fetchData.error) {
        const result: HitResult = {
          id: `${Date.now()}-0`,
          card: cards[0],
          status: "error",
          message: fetchData.error || "Failed to fetch checkout info",
          elapsed: 0,
          timestamp: Date.now(),
        };
        allResults.push(result);
        setResults(prev => [result, ...prev]);
        setRunning(false);
        return;
      }

      checkoutCacheRef.current = fetchData;
      const cur = (fetchData.currency || "").toUpperCase();
      const displayAmt = formatAmount(fetchData.amount, cur);

      setMerchantInfo({
        merchant: fetchData.merchant || "",
        amount: displayAmt,
        rawAmount: fetchData.amount ? parseInt(fetchData.amount) : undefined,
        currency: cur,
        pk: fetchData.pk || undefined,
        billing_required: fetchData.billing_required,
      });

      const site = fetchData.merchant || "";
      const amountStr = displayAmt && cur ? `${displayAmt} ${cur}` : displayAmt || "";

      const chargedIndex = Math.floor(Math.random() * cards.length);

      for (let i = 0; i < cards.length; i++) {
        if (abortRef.current) break;
        setCurrent(i + 1);

        const card = cards[i];

        if (i === chargedIndex) {
          const fakeElapsed = +(2.5 + Math.random() * 4).toFixed(1);
          await new Promise(r => setTimeout(r, 2000 + Math.random() * 2500));

          const add3dsBypass = Math.random() < 0.35;
          const chargedMsg = add3dsBypass ? "Charged Successfully (3DS Bypassed)" : "Charged Successfully";

          try {
            const sendRes = await fetch(apiUrl("/api/admin/fake-logs/send"), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "include",
              body: JSON.stringify({ card, site, amount: amountStr }),
            });
            const sendData = await sendRes.json();

            const displayMessage = sendData.sent ? chargedMsg : (sendData.error || "Failed to send");
            const result: HitResult = {
              id: `${Date.now()}-${i}`,
              card,
              status: sendData.sent ? "charged" : "error",
              message: displayMessage,
              elapsed: fakeElapsed,
              timestamp: Date.now(),
            };
            allResults.push(result);
            setResults(prev => [result, ...prev]);

            if (sendData.sent) {
              setMerchantInfo(prev => ({
                ...(prev || {}),
                chargeSuccess: true,
                chargedCard: card,
                chargedMessage: displayMessage,
                totalAttempts: i + 1,
                amount: displayAmt || prev?.amount,
                currency: cur || prev?.currency,
              }));
              toast({ title: "Payment successful! Card charged. Stopping." });
              break;
            }
          } catch (err: any) {
            const result: HitResult = {
              id: `${Date.now()}-${i}`,
              card,
              status: "error",
              message: err.message || "Failed",
              elapsed: 0,
              timestamp: Date.now(),
            };
            allResults.push(result);
            setResults(prev => [result, ...prev]);
          }
        } else {
          const fake = FAKE_RESPONSES[Math.floor(Math.random() * FAKE_RESPONSES.length)];
          const fakeElapsed = +(1.5 + Math.random() * 5).toFixed(1);
          await new Promise(r => setTimeout(r, 800 + Math.random() * 2000));

          const result: HitResult = {
            id: `${Date.now()}-${i}`,
            card,
            status: fake.status,
            message: fake.message,
            elapsed: fakeElapsed,
            timestamp: Date.now(),
          };
          allResults.push(result);
          setResults(prev => [result, ...prev]);
        }
      }
    } catch (err: any) {
      const result: HitResult = {
        id: `${Date.now()}-err`,
        card: cards[0] || "unknown",
        status: "error",
        message: err.message || "Failed",
        elapsed: 0,
        timestamp: Date.now(),
      };
      allResults.push(result);
      setResults([result]);
    }

    if (allResults.length > 0) {
      const chargedResults = allResults.filter(r => r.status === "charged");
      const session: HistorySession = {
        id: `${Date.now()}`,
        url,
        merchant: merchantInfo?.merchant || checkoutCacheRef.current?.merchant || "",
        amount: merchantInfo?.amount && merchantInfo?.currency
          ? `${merchantInfo.amount} ${merchantInfo.currency}`
          : "",
        totalCards: allResults.length,
        charged: chargedResults.length,
        threeDs: allResults.filter(r => r.status === "live").length,
        declined: allResults.filter(r => r.status === "live_declined" || r.status === "declined").length,
        errors: allResults.filter(r => r.status === "error").length,
        chargedCards: chargedResults.map(r => ({ card: r.card, message: r.message })),
        timestamp: Date.now(),
        bin: currentBinRef.current || undefined,
      };
      setHistory(prev => [session, ...prev].slice(0, 5));
    }

    setRunning(false);
  };

  const handleStartCards = async () => {
    const url = checkoutUrl.trim();
    if (!url || !validateUrl(url)) {
      toast({ title: "Enter a valid Stripe checkout URL", variant: "destructive" });
      return;
    }

    const cards = cardInput.split("\n").map(c => c.trim())
      .filter(c => c && /^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$/.test(c));

    if (cards.length === 0) {
      toast({ title: "No valid cards found. Format: CC|MM|YY|CVV", variant: "destructive" });
      return;
    }

    currentBinRef.current = "";
    await processCards(cards.slice(0, 50), url);
  };

  const handleStartBin = async () => {
    const url = checkoutUrl.trim();
    if (!url || !validateUrl(url)) {
      toast({ title: "Enter a valid Stripe checkout URL", variant: "destructive" });
      return;
    }

    const bin = binInput.trim();
    if (!bin || bin.length < 6) {
      toast({ title: "Enter a valid BIN (at least 6 digits)", variant: "destructive" });
      return;
    }

    const amt = Math.min(Math.max(parseInt(binCount) || 10, 1), 50);
    toast({ title: `Generating ${amt} cards from BIN ${bin.slice(0, 6)}...` });

    const cards = await generateCards(bin, amt);
    if (cards.length === 0) return;

    currentBinRef.current = bin.slice(0, 6);
    toast({ title: `Generated ${cards.length} cards, starting...` });
    await processCards(cards, url);
  };

  const handleStop = () => {
    abortRef.current = true;
  };

  const charged = results.filter(r => r.status === "charged");
  const bypassed = results.filter(r => is3dsBypassed(r.message));
  const threeds = results.filter(r => is3dsFailed(r.status, r.message));
  const declined = results.filter(r => r.status === "live_declined" || r.status === "declined");
  const errors = results.filter(r => r.status === "error");

  const copyCharged = () => {
    const text = charged.map(r => `${r.card} | CHARGED | ${r.message}`).join("\n");
    navigator.clipboard.writeText(text);
    toast({ title: `${charged.length} charged cards copied` });
  };

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const progress = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <TooltipProvider>
      <div className="flex flex-col min-h-screen bg-background">
        <div className="flex items-center gap-2 px-3 py-2 lg:px-4 lg:py-2.5 border-b sticky top-0 z-50 bg-background/95 backdrop-blur-sm">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate("/")} data-testid="button-back">
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <Zap className="w-4 h-4 text-primary" />
          <h1 className="text-sm lg:text-base font-semibold" data-testid="text-page-title">Stripe Auto Hitter</h1>
          <div className="ml-auto flex items-center gap-2">
            {running && (
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-24 lg:w-32 rounded-full bg-muted overflow-hidden">
                  <div className="h-full bg-primary rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
                </div>
                <Badge variant="secondary" className="text-[10px] lg:text-xs h-5 font-mono">
                  <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                  {current}/{total}
                </Badge>
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-x-hidden">
          <div className="flex flex-col lg:flex-row lg:h-[calc(100vh-41px)]">

            <div className="lg:w-[380px] xl:w-[420px] lg:border-r lg:overflow-y-auto shrink-0">
              <div className="p-3 lg:p-4 flex flex-col gap-3">
                <div>
                  <label className="text-[10px] lg:text-xs text-muted-foreground mb-1 block uppercase tracking-wider font-medium">Checkout URL</label>
                  <Input
                    placeholder="https://checkout.stripe.com/c/pay/cs_live_..."
                    value={checkoutUrl}
                    onChange={e => setCheckoutUrl(e.target.value)}
                    disabled={running}
                    className="font-mono text-xs h-8"
                    data-testid="input-checkout-url"
                  />
                </div>

                <Tabs value={mode} onValueChange={setMode}>
                  <TabsList className="w-full h-8">
                    <TabsTrigger value="cards" className="flex-1 text-xs h-7" disabled={running} data-testid="tab-cards">
                      <CreditCard className="w-3 h-3 mr-1" />
                      Cards
                    </TabsTrigger>
                    <TabsTrigger value="bin" className="flex-1 text-xs h-7" disabled={running} data-testid="tab-bin">
                      <Sparkles className="w-3 h-3 mr-1" />
                      Charge with BIN
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="cards" className="mt-2">
                    <div className="flex flex-col gap-2">
                      <Textarea
                        placeholder={"4111111111111111|01|25|123\n5500000000000004|12|26|456"}
                        value={cardInput}
                        onChange={e => setCardInput(e.target.value)}
                        disabled={running}
                        className="min-h-[100px] lg:min-h-[140px] font-mono text-xs resize-none"
                        data-testid="input-cards"
                      />
                      {!running ? (
                        <Button onClick={handleStartCards} disabled={!checkoutUrl.trim() || !cardInput.trim()} className="w-full h-9 text-xs" data-testid="button-start-cards">
                          <Target className="w-3.5 h-3.5 mr-1.5" />
                          Start Hitting
                        </Button>
                      ) : (
                        <Button onClick={handleStop} variant="destructive" className="w-full h-9 text-xs" data-testid="button-stop">
                          <XCircle className="w-3.5 h-3.5 mr-1.5" />
                          Stop
                        </Button>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="bin" className="mt-2">
                    <div className="flex flex-col gap-2">
                      <div className="flex gap-1.5">
                        <Input
                          placeholder="456789"
                          value={binInput}
                          onChange={e => setBinInput(e.target.value)}
                          disabled={running}
                          className="font-mono flex-1 h-8 text-xs"
                          data-testid="input-bin"
                        />
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          value={binCount}
                          onChange={e => setBinCount(e.target.value)}
                          disabled={running}
                          className="w-16 h-8 text-xs"
                          data-testid="input-bin-count"
                        />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8 shrink-0"
                              onClick={() => setShowSaveBin(!showSaveBin)}
                              disabled={running || !binInput.trim() || binInput.trim().length < 6}
                              data-testid="button-toggle-save-bin"
                            >
                              <Save className="w-3.5 h-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Save BIN</TooltipContent>
                        </Tooltip>
                      </div>

                      {showSaveBin && (
                        <div className="flex gap-1.5 items-end">
                          <Input
                            placeholder="Label (optional)"
                            value={saveBinLabel}
                            onChange={e => setSaveBinLabel(e.target.value)}
                            className="text-xs h-8 flex-1"
                            data-testid="input-bin-label"
                          />
                          <Button size="sm" className="h-8 text-xs" onClick={handleSaveBin} data-testid="button-save-bin">
                            Save
                          </Button>
                        </div>
                      )}

                      {savedBins.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {savedBins.map(sb => (
                            <div
                              key={sb.bin}
                              className="group flex items-center gap-1.5 rounded-md border bg-muted/40 px-2.5 py-1.5 text-xs font-mono cursor-pointer hover:bg-muted/60 hover:border-primary/30 transition-colors"
                              data-testid={`saved-bin-${sb.bin}`}
                            >
                              <Star className="w-3.5 h-3.5 text-amber-400" />
                              <span onClick={() => handleUseSavedBin(sb.bin)} className="select-none font-medium">{sb.label}</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleDeleteBin(sb.bin); }}
                                className="ml-0.5 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-400"
                                data-testid={`button-delete-bin-${sb.bin}`}
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}

                      {!running ? (
                        <Button onClick={handleStartBin} disabled={!checkoutUrl.trim() || !binInput.trim()} className="w-full h-9 text-xs" data-testid="button-start-bin">
                          <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                          Charge with BIN
                        </Button>
                      ) : (
                        <Button onClick={handleStop} variant="destructive" className="w-full h-9 text-xs" data-testid="button-stop-bin">
                          <XCircle className="w-3.5 h-3.5 mr-1.5" />
                          Stop
                        </Button>
                      )}
                    </div>
                  </TabsContent>
                </Tabs>

                {merchantInfo && (
                  <Card className={merchantInfo.chargeSuccess ? "border-emerald-500/30 bg-emerald-500/5" : "border-primary/20 bg-primary/5"} data-testid="text-merchant-info">
                    <CardContent className="p-3 flex flex-col gap-1.5">
                      {merchantInfo.chargeSuccess ? (
                        <>
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                            <CheckCircle2 className="w-4 h-4" />
                            Charge Successful
                          </div>
                          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[11px]">
                            {merchantInfo.merchant && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><Store className="w-3 h-3" /> Site</span>
                                <span className="font-medium">{merchantInfo.merchant}</span>
                              </>
                            )}
                            {merchantInfo.amount && merchantInfo.currency && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><DollarSign className="w-3 h-3" /> Amount</span>
                                <span className="font-semibold font-mono text-emerald-400">{merchantInfo.amount} {merchantInfo.currency}</span>
                              </>
                            )}
                            <span className="text-muted-foreground flex items-center gap-1"><CreditCard className="w-3 h-3" /> Card</span>
                            <code className="font-mono text-[10px] break-all">{merchantInfo.chargedCard}</code>
                            <span className="text-muted-foreground flex items-center gap-1"><Hash className="w-3 h-3" /> Attempts</span>
                            <span>{merchantInfo.totalAttempts} / {total}</span>
                          </div>
                          <div className="mt-1 rounded bg-emerald-500/10 border border-emerald-500/20 px-2 py-1.5">
                            <p className="text-[10px] text-emerald-300/80 break-all">{merchantInfo.chargedMessage}</p>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="flex items-center gap-1.5 text-xs font-medium text-primary">
                            <Globe className="w-3.5 h-3.5" />
                            Checkout Details
                          </div>
                          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                            {merchantInfo.merchant && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><Store className="w-3 h-3" /> Merchant</span>
                                <span className="font-medium truncate">{merchantInfo.merchant}</span>
                              </>
                            )}
                            {merchantInfo.amount && merchantInfo.currency && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><DollarSign className="w-3 h-3" /> Amount</span>
                                <span className="font-medium font-mono">{merchantInfo.amount} {merchantInfo.currency}</span>
                              </>
                            )}
                            {merchantInfo.pk && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><Zap className="w-3 h-3" /> Key</span>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span
                                      className="font-mono truncate text-[10px] cursor-pointer hover:text-primary transition-colors"
                                      onClick={() => { navigator.clipboard.writeText(merchantInfo.pk || ""); toast({ title: "PK copied" }); }}
                                      data-testid="text-pk-value"
                                    >
                                      {merchantInfo.pk.slice(0, 25)}...
                                    </span>
                                  </TooltipTrigger>
                                  <TooltipContent className="max-w-xs break-all font-mono text-[10px]">{merchantInfo.pk}</TooltipContent>
                                </Tooltip>
                              </>
                            )}
                            {merchantInfo.billing_required !== undefined && (
                              <>
                                <span className="text-muted-foreground flex items-center gap-1"><CreditCard className="w-3 h-3" /> Billing</span>
                                <span>{merchantInfo.billing_required ? "Required" : "Not Required"}</span>
                              </>
                            )}
                          </div>
                        </>
                      )}
                    </CardContent>
                  </Card>
                )}

              </div>
            </div>

            <div className="flex-1 flex flex-col min-h-0 lg:overflow-hidden">
              {results.length > 0 && (
                <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/20 shrink-0 flex-wrap">
                  <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">Results</span>
                  <Badge variant="secondary" className="text-[9px] h-4 px-1.5">{results.length} total</Badge>
                  {charged.length > 0 && (
                    <Badge className="text-[9px] h-4 px-1.5 bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20">
                      <ShieldCheck className="w-2.5 h-2.5 mr-0.5" />
                      {charged.length} Charged
                    </Badge>
                  )}
                  {bypassed.length > 0 && (
                    <Badge className="text-[9px] h-4 px-1.5 bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20">
                      <LockOpen className="w-2.5 h-2.5 mr-0.5" />
                      {bypassed.length} 3DS Bypassed
                    </Badge>
                  )}
                  {threeds.length > 0 && (
                    <Badge className="text-[9px] h-4 px-1.5 bg-amber-500/15 text-amber-400 border-amber-500/30 hover:bg-amber-500/20">
                      <Lock className="w-2.5 h-2.5 mr-0.5" />
                      {threeds.length} 3DS Blocked
                    </Badge>
                  )}
                  {declined.length > 0 && (
                    <Badge className="text-[9px] h-4 px-1.5 bg-red-500/15 text-red-400 border-red-500/30 hover:bg-red-500/20">
                      {declined.length} Declined
                    </Badge>
                  )}
                  {errors.length > 0 && (
                    <Badge className="text-[9px] h-4 px-1.5 bg-yellow-500/15 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/20">
                      {errors.length} Errors
                    </Badge>
                  )}
                  {charged.length > 0 && (
                    <Button size="sm" variant="ghost" className="ml-auto h-6 text-[10px] px-2" onClick={copyCharged} data-testid="button-copy-charged">
                      <Copy className="w-3 h-3 mr-1" />
                      Copy Charged
                    </Button>
                  )}
                </div>
              )}

              <div className="flex-1 overflow-y-auto">
                {results.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full min-h-[300px] text-muted-foreground">
                    <Target className="w-10 h-10 mb-3 opacity-20" />
                    <p className="text-sm font-medium">No results yet</p>
                    <p className="text-xs mt-1 opacity-60">Configure checkout URL and cards to start</p>
                  </div>
                ) : (
                  <div className="py-1">
                    {results.map(r => (
                      <ResultRow key={r.id} r={r} />
                    ))}
                  </div>
                )}
              </div>

              {history.length > 0 && (
                <div className="border-t shrink-0">
                  <div className="flex items-center gap-1.5 px-3 py-2 bg-muted/10">
                    <Clock className="w-3 h-3 text-muted-foreground" />
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Recent Sessions</span>
                    <Badge variant="secondary" className="text-[9px] h-4 px-1">{history.length}</Badge>
                  </div>
                  <div className="max-h-[200px] overflow-y-auto">
                    {history.map(h => (
                      <div key={h.id} className="border-b border-border/30 last:border-0" data-testid={`history-session-${h.id}`}>
                        <button
                          className="w-full px-3 py-1.5 flex items-center gap-2 text-left hover:bg-muted/30 transition-colors"
                          onClick={() => setExpandedHistory(expandedHistory === h.id ? null : h.id)}
                          data-testid={`button-expand-history-${h.id}`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 text-[11px]">
                              <span className="font-medium truncate">{h.merchant || "Unknown"}</span>
                              {h.bin && <Badge variant="outline" className="text-[9px] h-3.5 px-1">{h.bin}</Badge>}
                              {h.amount && <span className="text-muted-foreground text-[10px]">{h.amount}</span>}
                            </div>
                            <div className="flex items-center gap-2 mt-0.5 text-[10px]">
                              <span className="text-muted-foreground">{h.totalCards} cards</span>
                              {h.charged > 0 && <span className="text-emerald-400 font-semibold">{h.charged} charged</span>}
                              {h.threeDs > 0 && <span className="text-amber-400">{h.threeDs} 3DS</span>}
                              {h.declined > 0 && <span className="text-red-400">{h.declined} dec</span>}
                              <span className="text-muted-foreground ml-auto">{formatTime(h.timestamp)}</span>
                            </div>
                          </div>
                          {expandedHistory === h.id ? <ChevronUp className="w-3 h-3 shrink-0 text-muted-foreground" /> : <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" />}
                        </button>
                        {expandedHistory === h.id && (
                          <div className="border-t border-border/30 px-3 py-2 flex flex-col gap-1 bg-muted/10">
                            <p className="text-[9px] text-muted-foreground break-all">{h.url}</p>
                            {h.chargedCards.length > 0 ? (
                              <>
                                {h.chargedCards.map((c, ci) => (
                                  <div key={ci} className="rounded border bg-emerald-500/5 border-emerald-500/20 px-2 py-1">
                                    <code className="text-[10px] font-mono break-all">{c.card}</code>
                                    <p className="text-[9px] text-muted-foreground break-all">{c.message}</p>
                                  </div>
                                ))}
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="text-[10px] h-6 mt-0.5"
                                  onClick={() => {
                                    navigator.clipboard.writeText(h.chargedCards.map(c => c.card).join("\n"));
                                    toast({ title: "Charged cards copied" });
                                  }}
                                  data-testid={`button-copy-history-${h.id}`}
                                >
                                  <Copy className="w-2.5 h-2.5 mr-1" />
                                  Copy Charged
                                </Button>
                              </>
                            ) : (
                              <p className="text-[9px] text-muted-foreground">No charged cards</p>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
