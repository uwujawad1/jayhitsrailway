import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  GraduationCap, ArrowLeft, Loader2, Plus, Trash2, XCircle,
  ShieldCheck, ShieldAlert, AlertCircle, User, Globe, Info, Eye, EyeOff, Copy, RefreshCw
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";
import { useAuth } from "@/lib/auth";

interface SkoolAccount {
  email: string;
  password: string;
  type: "global" | "user";
  status: "active" | "dead" | "unknown";
}

function getStatusBadge(status: string) {
  switch (status) {
    case "active":
      return <Badge variant="secondary" className="text-[10px] lg:text-xs bg-emerald-500/10 text-emerald-400 border-emerald-500/20">Active</Badge>;
    case "dead":
      return <Badge variant="secondary" className="text-[10px] lg:text-xs bg-red-500/10 text-red-400 border-red-500/20">Dead</Badge>;
    default:
      return <Badge variant="secondary" className="text-[10px] lg:text-xs bg-yellow-500/10 text-yellow-400 border-yellow-500/20">Unknown</Badge>;
  }
}

const SKOOL_GATEWAYS = [
  { id: "skl", name: "Stripe Auth $0.1", desc: "Auth check via Skool + Stripe SetupIntent", type: "auth" },
  { id: "skl1", name: "Stripe Charge $1", desc: "Charge $1 via paid Skool group", type: "charge" },
  { id: "skl2", name: "Stripe Charge $7", desc: "Charge $7 via paid Skool group", type: "charge" },
  { id: "auto", name: "Stripe Random Charge", desc: "Auto-pick Skool group for random amount charge", type: "charge" },
];

export default function SkoolGatePage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [adding, setAdding] = useState(false);
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [checking, setChecking] = useState<Record<string, boolean>>({});

  const { data: accountsData, isLoading } = useQuery<{ accounts: SkoolAccount[]; count: number }>({
    queryKey: ["/api/skool/accounts"],
  });

  const accounts = accountsData?.accounts || [];
  const globalAccounts = accounts.filter(a => a.type === "global");
  const userAccounts = accounts.filter(a => a.type === "user");
  const activeCount = accounts.filter(a => a.status === "active").length;
  const deadCount = accounts.filter(a => a.status === "dead").length;

  const togglePassword = (email: string) => {
    setShowPasswords(prev => ({ ...prev, [email]: !prev[email] }));
  };

  const copyCredentials = (email: string, password: string) => {
    navigator.clipboard.writeText(`${email}:${password}`);
    toast({ title: "Credentials copied" });
  };

  const addAccount = async () => {
    if (!newEmail.trim() || !newPassword.trim()) {
      toast({ title: "Email and password required", variant: "destructive" });
      return;
    }
    setAdding(true);
    try {
      const res = await apiRequest("POST", "/api/skool/accounts", {
        email: newEmail.trim(),
        password: newPassword.trim(),
      });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
      } else {
        toast({ title: `Account added (${data.type})` });
        setNewEmail("");
        setNewPassword("");
        queryClient.invalidateQueries({ queryKey: ["/api/skool/accounts"] });
      }
    } catch (err: any) {
      toast({ title: err.message || "Failed to add account", variant: "destructive" });
    }
    setAdding(false);
  };

  const checkAccount = async (email: string, password: string) => {
    setChecking(prev => ({ ...prev, [email]: true }));
    try {
      const res = await apiRequest("POST", "/api/skool/accounts/check", { email, password });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
      } else {
        const statusLabel = data.status === "active" ? "Active" : data.status === "dead" ? "Dead" : "Unknown";
        toast({ title: `${statusLabel}: ${data.detail || "Check complete"}` });
        queryClient.invalidateQueries({ queryKey: ["/api/skool/accounts"] });
      }
    } catch (err: any) {
      toast({ title: err.message || "Check failed", variant: "destructive" });
    }
    setChecking(prev => ({ ...prev, [email]: false }));
  };

  const checkAllAccounts = async () => {
    for (const acc of accounts) {
      await checkAccount(acc.email, acc.password);
    }
  };

  const removeAccount = async (email: string) => {
    try {
      await apiRequest("DELETE", "/api/skool/accounts", { email });
      queryClient.invalidateQueries({ queryKey: ["/api/skool/accounts"] });
      toast({ title: "Account removed" });
    } catch (err: any) {
      toast({ title: err.message || "Failed to remove", variant: "destructive" });
    }
  };

  const renderAccount = (acc: SkoolAccount, prefix: string, i: number) => (
    <div key={`${prefix}-${i}`} className="flex flex-col gap-1 lg:gap-1.5 rounded-md border px-3 lg:px-4 py-2 lg:py-3 bg-muted/30 transition-all duration-300 hover:bg-muted/50" data-testid={`${prefix}-account-${i}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-xs lg:text-sm font-mono break-all" data-testid={`text-email-${prefix}-${i}`}>{acc.email}</span>
          {getStatusBadge(acc.status)}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button size="icon" variant="ghost" className="h-6 w-6 lg:h-7 lg:w-7 transition-all duration-300" onClick={() => checkAccount(acc.email, acc.password)} disabled={checking[acc.email]} data-testid={`button-check-${prefix}-${i}`}>
            {checking[acc.email] ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <RefreshCw className="w-3 h-3 lg:w-4 lg:h-4" />}
          </Button>
          <Button size="icon" variant="ghost" className="h-6 w-6 lg:h-7 lg:w-7 transition-all duration-300" onClick={() => copyCredentials(acc.email, acc.password)} data-testid={`button-copy-${prefix}-${i}`}>
            <Copy className="w-3 h-3 lg:w-4 lg:h-4" />
          </Button>
          <Button size="icon" variant="ghost" className="h-6 w-6 lg:h-7 lg:w-7 transition-all duration-300" onClick={() => removeAccount(acc.email)} data-testid={`button-remove-${prefix}-${i}`}>
            <Trash2 className="w-3 h-3 lg:w-4 lg:h-4 text-destructive" />
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] lg:text-xs text-muted-foreground">Password:</span>
        <code className="text-[11px] lg:text-sm font-mono break-all" data-testid={`text-password-${prefix}-${i}`}>
          {showPasswords[acc.email] ? acc.password : "••••••••"}
        </code>
        <Button size="icon" variant="ghost" className="h-5 w-5 lg:h-6 lg:w-6 transition-all duration-300" onClick={() => togglePassword(acc.email)} data-testid={`button-toggle-pass-${prefix}-${i}`}>
          {showPasswords[acc.email] ? <EyeOff className="w-3 h-3 lg:w-4 lg:h-4" /> : <Eye className="w-3 h-3 lg:w-4 lg:h-4" />}
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <div className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back" className="transition-all duration-300">
          <ArrowLeft className="w-4 h-4 lg:w-5 lg:h-5" />
        </Button>
        <GraduationCap className="w-5 h-5 lg:w-6 lg:h-6 text-primary transition-transform duration-300 hover:scale-110" />
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Skool Gate</h1>
      </div>

      <div className="flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-6 lg:p-8">
        <div className="max-w-2xl lg:max-w-5xl mx-auto flex flex-col gap-4 lg:gap-6">
          <Card className="animate-fade-in-up">
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                <Info className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                How It Works
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
              <div className="text-xs lg:text-sm text-muted-foreground flex flex-col gap-2 lg:gap-3">
                <p>Skool Gate uses Skool.com accounts integrated with Stripe to validate credit cards. The bot logs into your Skool account, sets up a Stripe PaymentMethod, and confirms a SetupIntent to check if the card is live.</p>
                <p><span className="font-semibold text-foreground">Auth gates</span> (like skl) validate the card with a $0 auth — no actual charge. <span className="font-semibold text-foreground">Charge gates</span> (like skl1, skl2) attempt to join a paid Skool group to verify the card can be charged, then immediately cancel.</p>
                <p><span className="font-semibold text-foreground">Accounts</span> are Skool.com login credentials (email + password). Each account needs a valid Skool login. Dead accounts are auto-removed after 3 consecutive login failures. Add your own accounts below to use these gateways.</p>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-3 gap-2 lg:gap-4">
            <Card className="p-3 lg:p-5 transition-all duration-300 hover:scale-[1.02] hover:shadow-md animate-fade-in-up" style={{ animationDelay: "50ms" }}>
              <div className="flex flex-col items-center gap-1 lg:gap-2">
                <span className="text-lg lg:text-2xl font-bold text-primary" data-testid="text-total-accounts">{accounts.length}</span>
                <span className="text-[10px] lg:text-xs text-muted-foreground">Total</span>
              </div>
            </Card>
            <Card className="p-3 lg:p-5 transition-all duration-300 hover:scale-[1.02] hover:shadow-md animate-fade-in-up" style={{ animationDelay: "100ms" }}>
              <div className="flex flex-col items-center gap-1 lg:gap-2">
                <span className="text-lg lg:text-2xl font-bold text-emerald-400" data-testid="text-active-accounts">{activeCount}</span>
                <span className="text-[10px] lg:text-xs text-muted-foreground">Active</span>
              </div>
            </Card>
            <Card className="p-3 lg:p-5 transition-all duration-300 hover:scale-[1.02] hover:shadow-md animate-fade-in-up" style={{ animationDelay: "150ms" }}>
              <div className="flex flex-col items-center gap-1 lg:gap-2">
                <span className="text-lg lg:text-2xl font-bold text-red-400" data-testid="text-dead-accounts">{deadCount}</span>
                <span className="text-[10px] lg:text-xs text-muted-foreground">Dead</span>
              </div>
            </Card>
          </div>

          <Card className="animate-fade-in-up" style={{ animationDelay: "200ms" }}>
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                Skool Gateways
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
              <div className="flex flex-col gap-2 lg:gap-3">
                {SKOOL_GATEWAYS.map(gw => (
                  <div key={gw.id} className="flex items-center justify-between gap-2 rounded-md border p-2 lg:p-3 bg-muted/30 transition-all duration-300 hover:bg-muted/50" data-testid={`gateway-${gw.id}`}>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        {gw.type === "auth"
                          ? <ShieldCheck className="w-3 h-3 lg:w-4 lg:h-4 text-blue-400 shrink-0" />
                          : <ShieldAlert className="w-3 h-3 lg:w-4 lg:h-4 text-yellow-400 shrink-0" />
                        }
                        <span className="text-xs lg:text-sm font-medium">{gw.name}</span>
                        <Badge variant="outline" className="text-[10px] lg:text-xs">{gw.type}</Badge>
                      </div>
                      <p className="text-[10px] lg:text-xs text-muted-foreground mt-0.5 ml-5 lg:ml-6">{gw.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in-up" style={{ animationDelay: "250ms" }}>
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                <Plus className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                Add Skool Account
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0 flex flex-col gap-3 lg:gap-4">
              <Input
                placeholder="email@example.com"
                value={newEmail}
                onChange={e => setNewEmail(e.target.value)}
                className="font-mono text-xs lg:text-sm"
                data-testid="input-email"
              />
              <Input
                type="password"
                placeholder="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                className="font-mono text-xs lg:text-sm"
                data-testid="input-password"
              />
              <Button onClick={addAccount} disabled={adding || !newEmail.trim() || !newPassword.trim()} className="w-full transition-all duration-300" data-testid="button-add-account">
                {adding ? <Loader2 className="w-4 h-4 lg:w-5 lg:h-5 mr-1 animate-spin" /> : <Plus className="w-4 h-4 lg:w-5 lg:h-5 mr-1" />}
                Add Account {isAdmin ? "(Global)" : "(Personal)"}
              </Button>
              <p className="text-[10px] lg:text-xs text-muted-foreground">
                {isAdmin
                  ? "As admin, accounts are added to the global pool shared with all users."
                  : "Accounts are added to your personal pool and used only for your checks."
                }
              </p>
            </CardContent>
          </Card>

          <Card className="animate-fade-in-up" style={{ animationDelay: "300ms" }}>
            <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
              <CardTitle className="text-sm lg:text-lg flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <User className="w-4 h-4 lg:w-5 lg:h-5 transition-transform duration-300 hover:scale-110" />
                  Accounts
                  <Badge variant="secondary" className="text-xs lg:text-sm">{accounts.length}</Badge>
                </span>
                {accounts.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs lg:text-sm h-7 lg:h-8 transition-all duration-300"
                    onClick={checkAllAccounts}
                    disabled={Object.values(checking).some(Boolean)}
                    data-testid="button-check-all"
                  >
                    {Object.values(checking).some(Boolean) ? <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />}
                    Check All
                  </Button>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
              {isLoading ? (
                <div className="flex items-center gap-2 text-xs lg:text-sm text-muted-foreground py-2">
                  <Loader2 className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" />
                  Loading accounts...
                </div>
              ) : accounts.length === 0 ? (
                <div className="flex flex-col items-center py-6 lg:py-8 text-muted-foreground">
                  <AlertCircle className="w-6 h-6 lg:w-8 lg:h-8 mb-2 opacity-30" />
                  <p className="text-xs lg:text-sm">No accounts found</p>
                  <p className="text-[10px] lg:text-xs mt-1">Add a Skool account above to get started</p>
                </div>
              ) : (
                <div className="flex flex-col gap-3 lg:gap-4">
                  {isAdmin && globalAccounts.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2 lg:mb-3">
                        <Globe className="w-3 h-3 lg:w-4 lg:h-4 text-muted-foreground" />
                        <span className="text-[10px] lg:text-xs text-muted-foreground font-semibold">Global Accounts</span>
                      </div>
                      <div className="flex flex-col gap-1 lg:gap-2">
                        {globalAccounts.map((acc, i) => renderAccount(acc, "global", i))}
                      </div>
                    </div>
                  )}

                  {userAccounts.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2 lg:mb-3">
                        <User className="w-3 h-3 lg:w-4 lg:h-4 text-muted-foreground" />
                        <span className="text-[10px] lg:text-xs text-muted-foreground font-semibold">Your Accounts</span>
                      </div>
                      <div className="flex flex-col gap-1 lg:gap-2">
                        {userAccounts.map((acc, i) => renderAccount(acc, "user", i))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
