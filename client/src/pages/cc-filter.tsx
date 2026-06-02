import { useState, useRef } from "react";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Filter, Loader2, Copy, ArrowLeft, Trash2, CreditCard, Upload, Globe
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";

interface BinInfo {
  country: string;
  country_code: string;
  flag: string;
  bank: string;
  brand: string;
  type: string;
  level: string;
}

interface FilterResult {
  total: number;
  unique_bins: number;
  by_bin: Record<string, number>;
  by_type: Record<string, number>;
  by_country: Record<string, number>;
  cards: string[];
  bins: Record<string, string[]>;
  types: Record<string, string[]>;
  countries: Record<string, string[]>;
  bin_info: Record<string, BinInfo>;
}

export default function CCFilterPage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<FilterResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [filterBy, setFilterBy] = useState<string>("");
  const [filteredCards, setFilteredCards] = useState<string[]>([]);
  const { toast } = useToast();
  const [, navigate] = useLocation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFilter = async () => {
    if (!input.trim()) {
      toast({ title: "Paste cards to filter", variant: "destructive" });
      return;
    }

    setLoading(true);
    setFilterBy("");
    setFilteredCards([]);
    try {
      const res = await apiRequest("POST", "/api/tools/filter", { cards: input });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
      } else {
        setResult(data);
        setFilteredCards(data.cards);
      }
    } catch (err: any) {
      toast({ title: err.message || "Filter failed", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      if (text) {
        setInput(prev => prev ? prev + "\n" + text : text);
        toast({ title: `Loaded ${file.name}` });
      }
    };
    reader.readAsText(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const applyFilter = (value: string) => {
    setFilterBy(value);
    if (!result) return;

    if (value === "all") {
      setFilteredCards(result.cards);
    } else if (value.startsWith("bin:")) {
      const binKey = value.replace("bin:", "");
      setFilteredCards(result.bins[binKey] || []);
    } else if (value.startsWith("type:")) {
      const typeKey = value.replace("type:", "");
      setFilteredCards(result.types[typeKey] || []);
    } else if (value.startsWith("country:")) {
      const countryKey = value.replace("country:", "");
      setFilteredCards(result.countries[countryKey] || []);
    }
  };

  const copyFiltered = () => {
    navigator.clipboard.writeText(filteredCards.join("\n"));
    toast({ title: `${filteredCards.length} cards copied` });
  };

  const uniqueCountries = result ? Object.keys(result.by_country).length : 0;

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <div className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back">
          <ArrowLeft className="w-4 h-4 lg:w-5 lg:h-5" />
        </Button>
        <Filter className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">CC Filter</h1>
      </div>

      <div className="flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <Card className="animate-fade-in-up">
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center justify-between">
                <span>Paste Cards</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  className="transition-all duration-300"
                  data-testid="button-upload-file"
                >
                  <Upload className="w-3.5 h-3.5 lg:w-4 lg:h-4 mr-1" />
                  Upload File
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3 flex flex-col gap-3 lg:gap-4">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.csv,.text"
                className="hidden"
                onChange={handleFileUpload}
                data-testid="input-file-upload"
              />
              <Textarea
                placeholder={"Paste cards here or upload a .txt file...\n4111111111111111|12|25|123\n5500000000000004|06|26|456"}
                value={input}
                onChange={e => setInput(e.target.value)}
                disabled={loading}
                className="min-h-[150px] lg:min-h-[200px] font-mono text-xs lg:text-sm resize-none"
                data-testid="input-cards"
              />
              <div className="flex gap-2">
                <Button onClick={handleFilter} disabled={loading || !input.trim()} className="flex-1 transition-all duration-300" data-testid="button-filter">
                  {loading ? <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2 animate-spin" /> : <Filter className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />}
                  {loading ? "Analyzing BINs..." : "Filter & Analyze"}
                </Button>
                {input && (
                  <Button variant="ghost" size="icon" onClick={() => { setInput(""); setResult(null); setFilteredCards([]); setFilterBy(""); }} className="transition-all duration-300" data-testid="button-clear-input">
                    <Trash2 className="w-4 h-4 lg:w-5 lg:h-5" />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {result && (
            <>
              <div className="grid grid-cols-4 gap-2 lg:gap-4">
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "0ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-primary" data-testid="text-total">{result.total}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Total</span>
                  </div>
                </Card>
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "50ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-blue-400" data-testid="text-bins">{result.unique_bins}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">BINs</span>
                  </div>
                </Card>
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "100ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-emerald-400" data-testid="text-types">{Object.keys(result.by_type).length}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Types</span>
                  </div>
                </Card>
                <Card className="p-3 lg:p-5 animate-fade-in-up transition-all duration-300 hover:scale-[1.02] hover:shadow-md" style={{ animationDelay: "150ms" }}>
                  <div className="flex flex-col items-center">
                    <span className="text-lg lg:text-2xl font-bold text-yellow-400" data-testid="text-countries">{uniqueCountries}</span>
                    <span className="text-[10px] lg:text-xs text-muted-foreground">Countries</span>
                  </div>
                </Card>
              </div>

              <Card className="animate-fade-in-up" style={{ animationDelay: "200ms" }}>
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3 flex flex-row items-center justify-between gap-2">
                  <CardTitle className="text-sm lg:text-lg">
                    Filter Results
                    <Badge variant="secondary" className="ml-2 text-xs lg:text-sm">{filteredCards.length}</Badge>
                  </CardTitle>
                  <Button size="icon" variant="ghost" onClick={copyFiltered} className="transition-all duration-300" data-testid="button-copy-filtered">
                    <Copy className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
                  </Button>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0 lg:pt-3 flex flex-col gap-3 lg:gap-4">
                  <Select value={filterBy} onValueChange={applyFilter}>
                    <SelectTrigger data-testid="select-filter">
                      <SelectValue placeholder="Filter by..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Cards ({result.total})</SelectItem>

                      {Object.keys(result.by_country).length > 0 && (
                        <>
                          <div className="px-2 py-1.5 text-xs lg:text-sm font-semibold text-muted-foreground flex items-center gap-1">
                            <Globe className="w-3 h-3 lg:w-4 lg:h-4" />
                            By Country
                          </div>
                          {Object.entries(result.by_country).map(([country, cards]) => {
                            const firstBin = Object.keys(result.bin_info).find(b => result.bin_info[b]?.country === country);
                            const flag = firstBin ? result.bin_info[firstBin]?.flag || "" : "";
                            return (
                              <SelectItem key={`country:${country}`} value={`country:${country}`}>
                                {flag} {country} ({cards.length})
                              </SelectItem>
                            );
                          })}
                        </>
                      )}

                      <div className="px-2 py-1.5 text-xs lg:text-sm font-semibold text-muted-foreground flex items-center gap-1">
                        <CreditCard className="w-3 h-3 lg:w-4 lg:h-4" />
                        By Type
                      </div>
                      {Object.entries(result.by_type).map(([type, count]) => (
                        <SelectItem key={`type:${type}`} value={`type:${type}`}>
                          {type} ({count})
                        </SelectItem>
                      ))}

                      <div className="px-2 py-1.5 text-xs lg:text-sm font-semibold text-muted-foreground">By BIN</div>
                      {Object.entries(result.by_bin).slice(0, 30).map(([binKey, count]) => {
                        const info = result.bin_info?.[binKey];
                        const extra = info ? ` ${info.flag || ""} ${info.bank || ""}`.trim() : "";
                        return (
                          <SelectItem key={`bin:${binKey}`} value={`bin:${binKey}`}>
                            {binKey} ({count}){extra ? ` - ${extra}` : ""}
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>

                  <div className="max-h-[300px] lg:max-h-[400px] overflow-y-auto">
                    <div className="font-mono text-xs lg:text-sm flex flex-col gap-0.5 lg:gap-1">
                      {filteredCards.map((c, i) => (
                        <div key={i} className="text-muted-foreground hover:text-foreground break-all transition-colors duration-200" data-testid={`text-card-${i}`}>{c}</div>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
