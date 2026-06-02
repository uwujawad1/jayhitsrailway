import { useState } from "react";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CreditCard, Loader2, Copy, ArrowLeft, Sparkles, Trash2
} from "lucide-react";
import { PageTransition } from "@/components/page-transition";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";

interface GenResult {
  cards: string[];
  bin_info: {
    brand: string;
    country: string;
    flag: string;
    bank: string;
    level: string;
    type: string;
  };
  count: number;
  error?: string;
}

export default function CCGeneratorPage() {
  const [bin, setBin] = useState("");
  const [amount, setAmount] = useState("10");
  const [month, setMonth] = useState("");
  const [year, setYear] = useState("");
  const [cvv, setCvv] = useState("");
  const [result, setResult] = useState<GenResult | null>(null);
  const [loading, setLoading] = useState(false);
  const { toast } = useToast();
  const [, navigate] = useLocation();

  const handleGenerate = async () => {
    if (!bin.trim() || bin.replace(/x/gi, "").length < 6) {
      toast({ title: "Enter at least 6 BIN digits", variant: "destructive" });
      return;
    }

    setLoading(true);
    try {
      const res = await apiRequest("POST", "/api/tools/generate", {
        bin: bin.trim(),
        amount: Number(amount) || 10,
        month: month || "xx",
        year: year || "xx",
        cvv: cvv || "xxx",
      });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
      } else {
        setResult(data);
      }
    } catch (err: any) {
      toast({ title: err.message || "Generation failed", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const copyCards = () => {
    if (!result?.cards) return;
    navigator.clipboard.writeText(result.cards.join("\n"));
    toast({ title: `${result.cards.length} cards copied` });
  };

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <div className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back">
          <ArrowLeft className="w-4 h-4 lg:w-5 lg:h-5" />
        </Button>
        <Sparkles className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">CC Generator</h1>
      </div>
      <PageTransition>

      <div className="flex-1 overflow-x-hidden p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <Card className="animate-fade-in-up">
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg">Generate Cards</CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3 flex flex-col gap-3 lg:gap-4">
              <div className="grid grid-cols-2 gap-3 lg:gap-4">
                <div className="col-span-2">
                  <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">BIN (6-16 digits, use x for random)</label>
                  <Input
                    placeholder="456789xxxxxxxxxx"
                    value={bin}
                    onChange={e => setBin(e.target.value.replace(/[^0-9xX]/g, ""))}
                    disabled={loading}
                    maxLength={16}
                    className="font-mono"
                    data-testid="input-bin"
                  />
                </div>
                <div>
                  <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">Amount (1-100)</label>
                  <Input
                    placeholder="10"
                    value={amount}
                    onChange={e => setAmount(e.target.value.replace(/\D/g, ""))}
                    disabled={loading}
                    maxLength={3}
                    data-testid="input-amount"
                  />
                </div>
                <div>
                  <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">Month (empty = random)</label>
                  <Input
                    placeholder="MM"
                    value={month}
                    onChange={e => setMonth(e.target.value.replace(/\D/g, "").slice(0, 2))}
                    disabled={loading}
                    maxLength={2}
                    data-testid="input-month"
                  />
                </div>
                <div>
                  <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">Year (empty = random)</label>
                  <Input
                    placeholder="YY or YYYY"
                    value={year}
                    onChange={e => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
                    disabled={loading}
                    maxLength={4}
                    data-testid="input-year"
                  />
                </div>
                <div>
                  <label className="text-xs lg:text-sm text-muted-foreground mb-1 block">CVV (empty = random)</label>
                  <Input
                    placeholder="CVV"
                    value={cvv}
                    onChange={e => setCvv(e.target.value.replace(/\D/g, "").slice(0, 4))}
                    disabled={loading}
                    maxLength={4}
                    data-testid="input-cvv"
                  />
                </div>
              </div>
              <Button onClick={handleGenerate} disabled={loading || !bin.trim()} className="transition-all duration-300" data-testid="button-generate">
                {loading ? <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />}
                Generate
              </Button>
            </CardContent>
          </Card>

          {result && (
            <>
              <Card className="animate-fade-in-up" style={{ animationDelay: "50ms" }}>
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between">
                  <CardTitle className="text-sm lg:text-lg">BIN Info</CardTitle>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3">
                  <div className="grid grid-cols-2 gap-2 lg:gap-3 text-xs lg:text-sm">
                    <div>
                      <span className="text-muted-foreground">Brand:</span>
                      <span className="ml-2 font-medium" data-testid="text-brand">{result.bin_info.brand}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Type:</span>
                      <span className="ml-2 font-medium" data-testid="text-type">{result.bin_info.type}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Level:</span>
                      <span className="ml-2 font-medium">{result.bin_info.level}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Bank:</span>
                      <span className="ml-2 font-medium">{result.bin_info.bank}</span>
                    </div>
                    <div className="col-span-2">
                      <span className="text-muted-foreground">Country:</span>
                      <span className="ml-2 font-medium">{result.bin_info.country} {result.bin_info.flag}</span>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="animate-fade-in-up" style={{ animationDelay: "100ms" }}>
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between">
                  <CardTitle className="text-sm lg:text-lg">
                    Generated Cards
                    <Badge variant="secondary" className="ml-2 text-xs lg:text-sm">{result.count}</Badge>
                  </CardTitle>
                  <Button size="icon" variant="ghost" onClick={copyCards} className="transition-all duration-300" data-testid="button-copy-cards">
                    <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                  </Button>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3">
                  <ScrollArea className="h-[300px] lg:h-[400px]">
                    <div className="font-mono text-xs lg:text-sm flex flex-col gap-0.5 lg:gap-1">
                      {result.cards.map((c, i) => (
                        <div key={i} className="text-muted-foreground hover:text-foreground break-all transition-colors duration-200" data-testid={`text-card-${i}`}>{c}</div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
      </PageTransition>
    </div>
  );
}
