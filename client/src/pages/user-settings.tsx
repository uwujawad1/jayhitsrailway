import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, Globe, Key, Loader2, Plus, Trash2, CheckCircle2, Shield, ListPlus
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";

interface SettingsData {
  proxies: string[];
  skKeys: string[];
}

interface TierInfo {
  tier: string;
}

function maskSk(sk: string) {
  if (sk.length <= 12) return sk;
  return sk.slice(0, 8) + "..." + sk.slice(-4);
}

export default function UserSettingsPage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const [proxyInput, setProxyInput] = useState("");
  const [skInput, setSkInput] = useState("");
  const [addingProxy, setAddingProxy] = useState(false);
  const [bulkProxyInput, setBulkProxyInput] = useState("");
  const [showBulkAdd, setShowBulkAdd] = useState(false);
  const [addingBulk, setAddingBulk] = useState(false);
  const [validatingProxy, setValidatingProxy] = useState(false);
  const [removingAllProxies, setRemovingAllProxies] = useState(false);
  const [addingSk, setAddingSk] = useState(false);
  const [deletingProxy, setDeletingProxy] = useState<string | null>(null);
  const [deletingSk, setDeletingSk] = useState<string | null>(null);


  const { data, isLoading } = useQuery<SettingsData>({
    queryKey: ["/api/user/settings"],
  });

  const { data: tierInfo } = useQuery<TierInfo>({
    queryKey: ["/api/user/tier"],
    staleTime: 60000,
  });

  const isPaidUser = tierInfo?.tier === "silver" || tierInfo?.tier === "gold";

  const handleAddProxy = async () => {
    const raw = proxyInput.trim();
    if (!raw) return;

    setAddingProxy(true);
    try {
      const res = await apiRequest("POST", "/api/user/settings/proxy", { proxy: raw });
      const result = await res.json();
      if (result.error) {
        toast({ title: "Failed", description: result.error, variant: "destructive" });
      } else {
        toast({ title: "Proxy added" });
        setProxyInput("");
        queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
      }
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    }
    setAddingProxy(false);
  };

  const handleBulkAddProxies = async () => {
    const raw = bulkProxyInput.trim();
    if (!raw) return;

    setAddingBulk(true);
    try {
      const res = await apiRequest("POST", "/api/user/settings/proxy/bulk", { proxies: raw });
      const result = await res.json();
      const parts = [];
      if (result.added > 0) parts.push(`${result.added} added`);
      if (result.skipped > 0) parts.push(`${result.skipped} duplicate`);
      if (result.invalid > 0) parts.push(`${result.invalid} invalid`);
      toast({ title: "Bulk Import Done", description: parts.join(", ") });
      setBulkProxyInput("");
      setShowBulkAdd(false);
      queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
    } catch (err: any) {
      let msg = "Bulk import failed";
      try { const parsed = JSON.parse(err.message.replace(/^\d+:\s*/, "")); msg = parsed.error || msg; } catch {}
      toast({ title: "Failed", description: msg, variant: "destructive" });
    }
    setAddingBulk(false);
  };

  const handleValidateProxy = async () => {
    const raw = proxyInput.trim();
    if (!raw) return;

    setValidatingProxy(true);
    try {
      const res = await apiRequest("POST", "/api/user/settings/proxy/validate", { proxy: raw });
      const result = await res.json();
      if (result.valid) {
        toast({
          title: result.tested ? "Proxy Working" : "Format Valid",
          description: result.message + (result.ip ? ` (IP: ${result.ip})` : ""),
        });
      } else {
        toast({ title: "Invalid Proxy", description: result.error || result.message, variant: "destructive" });
      }
    } catch (err: any) {
      toast({ title: "Validation Failed", description: err.message, variant: "destructive" });
    }
    setValidatingProxy(false);
  };

  const handleDeleteProxy = async (proxy: string) => {
    setDeletingProxy(proxy);
    try {
      await apiRequest("DELETE", "/api/user/settings/proxy", { proxy });
      queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
      toast({ title: "Proxy removed" });
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    }
    setDeletingProxy(null);
  };

  const handleRemoveAllProxies = async () => {
    setRemovingAllProxies(true);
    try {
      await apiRequest("DELETE", "/api/user/settings/proxy/all", {});
      queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
      toast({ title: "All proxies removed" });
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    }
    setRemovingAllProxies(false);
  };

  const handleAddSk = async () => {
    const raw = skInput.trim();
    if (!raw) return;

    setAddingSk(true);
    try {
      const res = await apiRequest("POST", "/api/user/settings/sk", { sk: raw });
      const result = await res.json();
      if (result.error) {
        toast({ title: "Failed", description: result.error, variant: "destructive" });
      } else {
        toast({ title: "SK key added" });
        setSkInput("");
        queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
      }
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    }
    setAddingSk(false);
  };

  const handleDeleteSk = async (sk: string) => {
    setDeletingSk(sk);
    try {
      await apiRequest("DELETE", "/api/user/settings/sk", { sk });
      queryClient.invalidateQueries({ queryKey: ["/api/user/settings"] });
      toast({ title: "SK key removed" });
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    }
    setDeletingSk(null);
  };

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <header className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back">
          <ArrowLeft className="w-5 h-5 lg:w-6 lg:h-6" />
        </Button>
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Settings</h1>
      </header>

      <div className="flex-1 p-3 md:p-6 lg:p-8">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin text-primary" />
          </div>
        ) : (
          <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
            <Card className="animate-fade-in-up">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <Globe className="w-4 h-4 lg:w-5 lg:h-5 text-blue-400 transition-transform duration-300 hover:scale-110" />
                  Proxies
                  <Badge variant="secondary" className="text-xs lg:text-sm">{data?.proxies?.length || 0}/20</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3 flex flex-col gap-3 lg:gap-4">
                <p className="text-[11px] lg:text-sm text-muted-foreground">
                  Supports: ip:port, ip:port:user:pass, http://ip:port, socks5://user:pass@ip:port
                </p>
                <div className="flex gap-2 lg:gap-3">
                  <Input
                    placeholder="ip:port:user:pass"
                    value={proxyInput}
                    onChange={e => setProxyInput(e.target.value)}
                    className="flex-1 font-mono text-xs lg:text-sm"
                    data-testid="input-proxy"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleValidateProxy}
                    disabled={!proxyInput.trim() || validatingProxy}
                    className="transition-all duration-300"
                    data-testid="button-validate-proxy"
                    title="Validate proxy"
                  >
                    {validatingProxy ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <CheckCircle2 className="w-3 h-3 lg:w-4 lg:h-4" />}
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleAddProxy}
                    disabled={!proxyInput.trim() || addingProxy}
                    className="transition-all duration-300"
                    data-testid="button-add-proxy"
                    title="Add proxy"
                  >
                    {addingProxy ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <Plus className="w-3 h-3 lg:w-4 lg:h-4" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowBulkAdd(!showBulkAdd)}
                    className="transition-all duration-300"
                    data-testid="button-toggle-bulk"
                    title="Bulk add proxies"
                  >
                    <ListPlus className="w-3 h-3 lg:w-4 lg:h-4" />
                  </Button>
                </div>

                {showBulkAdd && (
                  <div className="flex flex-col gap-2 lg:gap-3 p-3 lg:p-4 rounded-lg border bg-muted/20 animate-fade-in-up">
                    <p className="text-[11px] lg:text-sm font-medium">Bulk Add Proxies (one per line)</p>
                    <Textarea
                      placeholder={"ip:port:user:pass\nip:port:user:pass\nip:port:user:pass"}
                      value={bulkProxyInput}
                      onChange={e => setBulkProxyInput(e.target.value)}
                      className="font-mono text-xs lg:text-sm min-h-[100px] lg:min-h-[120px]"
                      data-testid="textarea-bulk-proxy"
                    />
                    <div className="flex items-center justify-between">
                      <p className="text-[10px] lg:text-xs text-muted-foreground">
                        {bulkProxyInput.trim() ? `${bulkProxyInput.trim().split("\n").filter(l => l.trim().length >= 5).length} proxies detected` : "Paste your proxy list"}
                      </p>
                      <Button
                        size="sm"
                        onClick={handleBulkAddProxies}
                        disabled={!bulkProxyInput.trim() || addingBulk}
                        className="transition-all duration-300"
                        data-testid="button-bulk-add"
                      >
                        {addingBulk ? (
                          <>
                            <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin mr-1" />
                            <span className="lg:text-sm">Adding...</span>
                          </>
                        ) : (
                          <>
                            <ListPlus className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />
                            <span className="lg:text-sm">Add All</span>
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                )}

                {data?.proxies && data.proxies.length > 0 ? (
                  <>
                    <div className="flex flex-col gap-1.5 lg:gap-2 max-h-[250px] lg:max-h-[350px] overflow-y-auto">
                      {data.proxies.map((p, i) => (
                        <div key={i} className="flex items-center gap-2 rounded border bg-muted/30 px-3 lg:px-4 py-2 lg:py-2.5 transition-all duration-300 hover:bg-muted/50" data-testid={`proxy-item-${i}`}>
                          <Globe className="w-3 h-3 lg:w-4 lg:h-4 text-muted-foreground shrink-0" />
                          <code className="text-xs lg:text-sm font-mono flex-1 break-all">{p}</code>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 lg:h-7 lg:w-7 p-0 text-destructive hover:text-destructive transition-all duration-300"
                            onClick={() => handleDeleteProxy(p)}
                            disabled={deletingProxy === p}
                            data-testid={`button-delete-proxy-${i}`}
                          >
                            {deletingProxy === p ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <Trash2 className="w-3 h-3 lg:w-4 lg:h-4" />}
                          </Button>
                        </div>
                      ))}
                    </div>
                    <Button
                      variant="destructive"
                      size="sm"
                      className="w-full transition-all duration-300"
                      onClick={handleRemoveAllProxies}
                      disabled={removingAllProxies}
                      data-testid="button-remove-all-proxies"
                    >
                      {removingAllProxies ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin mr-1" /> : <Trash2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />}
                      <span className="lg:text-sm">Remove All Proxies</span>
                    </Button>
                  </>
                ) : (
                  <p className="text-xs lg:text-sm text-muted-foreground py-1">No proxies added. Proxies prevent gateway timeouts during mass checking.</p>
                )}
              </CardContent>
            </Card>

            <Card className="animate-fade-in-up" style={{ animationDelay: "100ms" }}>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <Key className="w-4 h-4 lg:w-5 lg:h-5 text-amber-400 transition-transform duration-300 hover:scale-110" />
                  SK Keys
                  <Badge variant="secondary" className="text-xs lg:text-sm">{data?.skKeys?.length || 0}/10</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3 flex flex-col gap-3 lg:gap-4">
                <p className="text-[11px] lg:text-sm text-muted-foreground">
                  Stripe Secret Keys (sk_live_..., sk_test_..., rk_live_..., rk_test_...)
                </p>
                <div className="flex gap-2 lg:gap-3">
                  <Input
                    placeholder="sk_live_..."
                    value={skInput}
                    onChange={e => setSkInput(e.target.value)}
                    className="flex-1 font-mono text-xs lg:text-sm"
                    data-testid="input-sk"
                  />
                  <Button
                    size="sm"
                    onClick={handleAddSk}
                    disabled={!skInput.trim() || addingSk}
                    className="transition-all duration-300"
                    data-testid="button-add-sk"
                    title="Add SK key"
                  >
                    {addingSk ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <Plus className="w-3 h-3 lg:w-4 lg:h-4" />}
                  </Button>
                </div>

                {data?.skKeys && data.skKeys.length > 0 ? (
                  <div className="flex flex-col gap-1.5 lg:gap-2 max-h-[250px] lg:max-h-[350px] overflow-y-auto">
                    {data.skKeys.map((sk, i) => (
                      <div key={i} className="flex items-center gap-2 rounded border bg-muted/30 px-3 lg:px-4 py-2 lg:py-2.5 transition-all duration-300 hover:bg-muted/50" data-testid={`sk-item-${i}`}>
                        <Key className="w-3 h-3 lg:w-4 lg:h-4 text-muted-foreground shrink-0" />
                        <code className="text-xs lg:text-sm font-mono flex-1">{maskSk(sk)}</code>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 lg:h-7 lg:w-7 p-0 text-destructive hover:text-destructive transition-all duration-300"
                          onClick={() => handleDeleteSk(sk)}
                          disabled={deletingSk === sk}
                          data-testid={`button-delete-sk-${i}`}
                        >
                          {deletingSk === sk ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <Trash2 className="w-3 h-3 lg:w-4 lg:h-4" />}
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs lg:text-sm text-muted-foreground py-2">No SK keys added. SK keys are used for Stripe gateway checks.</p>
                )}
              </CardContent>
            </Card>

            <div className="rounded-lg border bg-muted/20 p-3 lg:p-5 animate-fade-in-up" style={{ animationDelay: "200ms" }}>
              <div className="flex items-start gap-2 lg:gap-3">
                <Shield className="w-4 h-4 lg:w-5 lg:h-5 text-muted-foreground mt-0.5 shrink-0" />
                <div className="text-[11px] lg:text-sm text-muted-foreground">
                  <p className="font-medium mb-1 lg:mb-2">How it works:</p>
                  <ul className="list-disc list-inside space-y-0.5 lg:space-y-1">
                    <li>Proxies are automatically used when checking cards in C-C Checker, Auto Hitter, and other tools</li>
                    <li>A random proxy from your list is selected for each check</li>
                    <li>Adding proxies helps bypass 3DS and regional restrictions</li>
                    <li>SK keys are used for Stripe-based gateway checks</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
