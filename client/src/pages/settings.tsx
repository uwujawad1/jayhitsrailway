import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Settings, Save, RotateCw, Eye, EyeOff, KeyRound, Hash, Link2, Users, Shield, Scan, CheckCircle2, Loader2, Phone, Webhook, ShieldCheck, ShieldOff, RefreshCw, Globe, Lock, Unlock, AlertTriangle, Target, Download, Database, Bot } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { apiRequest, apiUrl, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { useState, useEffect } from "react";

interface BotConfig {
  botToken: string;
  apiId: string;
  apiHash: string;
  adminId: string;
  groupId: string;
  groupLink: string;
  channelLink: string;
}

export default function SettingsPage() {
  const { toast } = useToast();
  const [showToken, setShowToken] = useState(false);
  const [showHash, setShowHash] = useState(false);

  const [botToken, setBotToken] = useState("");
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [adminId, setAdminId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [groupLink, setGroupLink] = useState("");
  const [channelLink, setChannelLink] = useState("");
  const [hasEdits, setHasEdits] = useState(false);
  const [scraperPhone, setScraperPhone] = useState("");
  const [scraperCode, setScraperCode] = useState("");
  const [scraperPassword, setScraperPassword] = useState("");
  const [scraperHash, setScraperHash] = useState("");
  const [scraperStep, setScraperStep] = useState<"idle" | "code_sent" | "needs_password" | "loading">("idle");
  const [scraperUser, setScraperUser] = useState<{firstName: string; username: string} | null>(null);
  const [nopechaKey, setNopechaKey] = useState("");
  const [captchaaiKey, setCaptchaaiKey] = useState("");
  const [showNopechaKey, setShowNopechaKey] = useState(false);
  const [captchaKeysSaved, setCaptchaKeysSaved] = useState(false);
  const [logsGroupId, setLogsGroupId] = useState("");
  const [logsGroupSaved, setLogsGroupSaved] = useState(false);

  const { data: config, isLoading } = useQuery<BotConfig>({
    queryKey: ["/api/bot/config"],
  });

  interface WebhookStatus {
    url: string;
    active: boolean;
    ours: boolean;
    pendingUpdateCount: number;
    lastError: string | null;
    expectedUrl: string;
  }

  const { data: webhookStatus, isLoading: webhookLoading, refetch: refetchWebhook } = useQuery<WebhookStatus>({
    queryKey: ["/api/admin/webhook/status"],
    refetchInterval: 30000,
  });

  const setupWebhookMutation = useMutation({
    mutationFn: () => apiRequest("POST", "/api/admin/webhook/setup"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/webhook/status"] });
      toast({ title: "✅ Webhook activated — getUpdates is now blocked for attackers" });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to set webhook", variant: "destructive" }),
  });

  const removeWebhookMutation = useMutation({
    mutationFn: () => apiRequest("POST", "/api/admin/webhook/remove"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/webhook/status"] });
      toast({ title: "Webhook removed" });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to remove webhook", variant: "destructive" }),
  });

  interface CfStatus {
    cfOnly: boolean;
    viaCf: boolean;
    cfRay: string | null;
    cfCountry: string | null;
    clientIp: string;
    remoteIp: string | null;
  }

  const { data: cfStatus, isLoading: cfLoading, refetch: refetchCf } = useQuery<CfStatus>({
    queryKey: ["/api/admin/cf/status"],
    refetchInterval: 60000,
  });

  const cfToggleMutation = useMutation({
    mutationFn: (cfOnly: boolean) => apiRequest("POST", "/api/admin/cf/toggle", { cfOnly }),
    onSuccess: (_, cfOnly) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/cf/status"] });
      toast({
        title: cfOnly
          ? "Cloudflare-only mode enabled — direct access blocked"
          : "Cloudflare-only mode disabled",
      });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to toggle", variant: "destructive" }),
  });

  const { data: maintenanceData, isLoading: maintenanceLoading } = useQuery<{ maintenance: boolean }>({
    queryKey: ["/api/admin/maintenance"],
  });

  const maintenanceMutation = useMutation({
    mutationFn: (maintenance: boolean) => apiRequest("POST", "/api/admin/maintenance", { maintenance }),
    onSuccess: (_, maintenance) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/maintenance"] });
      toast({
        title: maintenance ? "Maintenance mode ON — users see the maintenance popup" : "Maintenance mode OFF — app is live",
      });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to toggle maintenance", variant: "destructive" }),
  });

  const { data: hitterSiteData, isLoading: hitterSiteLoading } = useQuery<{ siteVisible: boolean }>({
    queryKey: ["/api/admin/hitter/site-visible"],
  });

  const hitterSiteMutation = useMutation({
    mutationFn: (siteVisible: boolean) => apiRequest("POST", "/api/admin/hitter/site-visible", { siteVisible }),
    onSuccess: (_, siteVisible) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/hitter/site-visible"] });
      toast({
        title: siteVisible
          ? "Group log will now show the site URL"
          : "Group log will now hide the site URL",
      });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to update setting", variant: "destructive" }),
  });

  const { data: sessionStatus, refetch: refetchSession } = useQuery<{ hasSession: boolean }>({
    queryKey: ["/api/tools/scraper-session-status"],
  });

  const { data: captchaKeys } = useQuery<{ nopechaKey: string; captchaaiKey: string }>({
    queryKey: ["/api/admin/captcha-keys"],
  });

  useEffect(() => {
    if (captchaKeys) {
      setNopechaKey(captchaKeys.nopechaKey || "");
      setCaptchaaiKey(captchaKeys.captchaaiKey || "");
    }
  }, [captchaKeys]);

  const saveCaptchaKeys = useMutation({
    mutationFn: () => apiRequest("PUT", "/api/admin/captcha-keys", { nopechaKey, captchaaiKey }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/captcha-keys"] });
      setCaptchaKeysSaved(true);
      setTimeout(() => setCaptchaKeysSaved(false), 2500);
      toast({ title: "Captcha keys saved — active immediately, no restart needed" });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to save keys", variant: "destructive" }),
  });

  const { data: logsConfig } = useQuery<{ logsGroupId: string }>({
    queryKey: ["/api/admin/logs-config"],
  });

  useEffect(() => {
    if (logsConfig) {
      setLogsGroupId(logsConfig.logsGroupId || "");
    }
  }, [logsConfig]);

  const saveLogsConfig = useMutation({
    mutationFn: () => apiRequest("PUT", "/api/admin/logs-config", { logsGroupId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/logs-config"] });
      setLogsGroupSaved(true);
      setTimeout(() => setLogsGroupSaved(false), 2500);
      toast({ title: "Logs Group ID saved successfully" });
    },
    onError: (err: any) => toast({ title: err.message || "Failed to save logs config", variant: "destructive" }),
  });

  useEffect(() => {
    if (config) {
      setBotToken(config.botToken);
      setApiId(config.apiId);
      setApiHash(config.apiHash);
      setAdminId(config.adminId);
      setGroupId(config.groupId);
      setGroupLink(config.groupLink);
      setChannelLink(config.channelLink || "");
      setHasEdits(false);
    }
  }, [config]);

  const saveConfig = useMutation({
    mutationFn: async () => {
      const body: Record<string, string> = {};
      if (botToken !== config?.botToken) body.botToken = botToken;
      if (apiId !== config?.apiId) body.apiId = apiId;
      if (apiHash !== config?.apiHash) body.apiHash = apiHash;
      if (adminId !== config?.adminId) body.adminId = adminId;
      if (groupId !== config?.groupId) body.groupId = groupId;
      if (groupLink !== config?.groupLink) body.groupLink = groupLink;
      if (channelLink !== config?.channelLink) body.channelLink = channelLink;
      return apiRequest("PUT", "/api/bot/config", body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/config"] });
      setHasEdits(false);
      toast({ title: "Settings saved", description: "Restart the bot to apply changes" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to save", description: err.message, variant: "destructive" });
    },
  });

  const restartBot = useMutation({
    mutationFn: () => apiRequest("POST", "/api/bot/restart"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/status"] });
      queryClient.invalidateQueries({ queryKey: ["/api/stats"] });
      toast({ title: "Bot restarting...", description: "The bot will use the updated settings" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to restart", description: err.message, variant: "destructive" });
    },
  });

  const handleFieldChange = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setter(e.target.value);
    setHasEdits(true);
  };

  const handleSendScraperCode = async () => {
    if (!scraperPhone.trim()) {
      toast({ title: "Enter phone number with country code", variant: "destructive" });
      return;
    }
    setScraperStep("loading");
    try {
      const res = await apiRequest("POST", "/api/tools/scraper-session/send-code", { phone: scraperPhone.trim() });
      const data = await res.json();
      if (data.error) {
        toast({ title: data.error, variant: "destructive" });
        setScraperStep("idle");
      } else {
        setScraperHash(data.phoneCodeHash);
        setScraperStep("code_sent");
        toast({ title: "Code sent to your Telegram app" });
      }
    } catch (err: any) {
      toast({ title: "Failed to send code", variant: "destructive" });
      setScraperStep("idle");
    }
  };

  const handleVerifyScraperCode = async () => {
    if (!scraperCode.trim()) {
      toast({ title: "Enter the verification code", variant: "destructive" });
      return;
    }
    setScraperStep("loading");
    try {
      const res = await apiRequest("POST", "/api/tools/scraper-session/verify", {
        phone: scraperPhone.trim(),
        code: scraperCode.trim(),
        phoneCodeHash: scraperHash,
        password: scraperPassword || undefined,
      });
      const data = await res.json();
      if (data.needs_password) {
        setScraperStep("needs_password");
        toast({ title: "2FA password required" });
      } else if (data.error) {
        toast({ title: data.error, variant: "destructive" });
        setScraperStep("code_sent");
      } else if (data.success) {
        setScraperUser({ firstName: data.user?.firstName || "", username: data.user?.username || "" });
        setScraperStep("idle");
        setScraperCode("");
        setScraperPassword("");
        setScraperHash("");
        refetchSession();
        toast({ title: data.message || "Session created successfully" });
      }
    } catch (err: any) {
      toast({ title: "Verification failed", variant: "destructive" });
      setScraperStep("code_sent");
    }
  };

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold" data-testid="text-page-title">Settings</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Configure your Telegram bot credentials
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            onClick={() => saveConfig.mutate()}
            disabled={saveConfig.isPending || !hasEdits}
            data-testid="button-save-config"
          >
            <Save className="w-4 h-4 mr-2" />
            {saveConfig.isPending ? "Saving..." : "Save Changes"}
          </Button>
          <Button
            variant="secondary"
            onClick={() => restartBot.mutate()}
            disabled={restartBot.isPending}
            data-testid="button-restart-bot"
          >
            <RotateCw className="w-4 h-4 mr-2" />
            {restartBot.isPending ? "Restarting..." : "Restart Bot"}
          </Button>
        </div>
      </div>

      {hasEdits && (
        <Badge variant="secondary" data-testid="badge-unsaved">
          Unsaved changes
        </Badge>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <KeyRound className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Bot Token</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">Telegram Bot Token</label>
            <div className="flex items-center gap-2">
              <Input
                type={showToken ? "text" : "password"}
                value={botToken}
                onChange={handleFieldChange(setBotToken)}
                placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                data-testid="input-bot-token"
              />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setShowToken(!showToken)}
                data-testid="button-toggle-token"
              >
                {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Get this from @BotFather on Telegram
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Shield className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Telegram API Credentials</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">API ID</label>
              <div className="flex items-center gap-2">
                <Hash className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <Input
                  value={apiId}
                  onChange={handleFieldChange(setApiId)}
                  placeholder="12345678"
                  data-testid="input-api-id"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">API Hash</label>
              <div className="flex items-center gap-2">
                <Input
                  type={showHash ? "text" : "password"}
                  value={apiHash}
                  onChange={handleFieldChange(setApiHash)}
                  placeholder="0123456789abcdef0123456789abcdef"
                  data-testid="input-api-hash"
                />
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => setShowHash(!showHash)}
                  data-testid="button-toggle-hash"
                >
                  {showHash ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </Button>
              </div>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Get these from my.telegram.org
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Settings className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Bot Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">Admin User IDs</label>
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              <Input
                value={adminId}
                onChange={handleFieldChange(setAdminId)}
                placeholder="123456789,987654321"
                data-testid="input-admin-id"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Comma-separated Telegram user IDs for admin access
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">Group ID</label>
              <div className="flex items-center gap-2">
                <Hash className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <Input
                  value={groupId}
                  onChange={handleFieldChange(setGroupId)}
                  placeholder="-1001234567890"
                  data-testid="input-group-id"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">Group Link</label>
              <div className="flex items-center gap-2">
                <Link2 className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <Input
                  value={groupLink}
                  onChange={handleFieldChange(setGroupLink)}
                  placeholder="https://t.me/yourgroup"
                  data-testid="input-group-link"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">Channel Link</label>
              <div className="flex items-center gap-2">
                <Link2 className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <Input
                  value={channelLink}
                  onChange={handleFieldChange(setChannelLink)}
                  placeholder="https://t.me/yourchannel"
                  data-testid="input-channel-link"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Scan className="w-5 h-5 text-primary" />
            Scraper Session
            {sessionStatus?.hasSession ? (
              <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">Active</Badge>
            ) : (
              <Badge variant="destructive">Not Set Up</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            The scraper needs a Telegram user session to read message history. Bots cannot access message history directly.
            Link a Telegram account that is a member of the groups/channels you want to scrape.
          </p>

          {scraperStep === "idle" && !sessionStatus?.hasSession && (
            <div className="space-y-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">Phone Number (with country code)</label>
                <div className="flex items-center gap-2">
                  <Phone className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                  <Input
                    value={scraperPhone}
                    onChange={e => setScraperPhone(e.target.value)}
                    placeholder="+1234567890"
                  />
                </div>
              </div>
              <Button onClick={handleSendScraperCode} className="w-full">
                Send Verification Code
              </Button>
            </div>
          )}

          {scraperStep === "loading" && (
            <div className="flex items-center justify-center p-4 gap-2 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
              Processing...
            </div>
          )}

          {scraperStep === "code_sent" && (
            <div className="space-y-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">Verification Code</label>
                <Input
                  value={scraperCode}
                  onChange={e => setScraperCode(e.target.value)}
                  placeholder="Enter code from Telegram"
                />
              </div>
              <Button onClick={handleVerifyScraperCode} className="w-full">
                Verify Code
              </Button>
            </div>
          )}

          {scraperStep === "needs_password" && (
            <div className="space-y-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-muted-foreground">2FA Password</label>
                <Input
                  type="password"
                  value={scraperPassword}
                  onChange={e => setScraperPassword(e.target.value)}
                  placeholder="Enter your 2FA password"
                />
              </div>
              <Button onClick={handleVerifyScraperCode} className="w-full">
                Submit Password
              </Button>
            </div>
          )}

          {sessionStatus?.hasSession && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              <div>
                <p className="text-sm font-medium text-emerald-400">Session Active</p>
                <p className="text-xs text-muted-foreground">
                  {scraperUser ? `${scraperUser.firstName} (@${scraperUser.username})` : "User session is linked and ready for scraping"}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Maintenance Mode Card ────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <AlertTriangle className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Maintenance Mode</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            When enabled, all users see a "maintenance" popup blocking the app. Admins are unaffected and can still use everything normally.
          </p>
          {maintenanceLoading ? (
            <div className="h-16 rounded-lg bg-muted animate-pulse" />
          ) : (
            <div className={`flex items-start justify-between gap-4 p-3 rounded-lg border ${maintenanceData?.maintenance ? "border-orange-500/50 bg-orange-500/10" : "border-border bg-muted/30"}`}>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <AlertTriangle className={`w-4 h-4 ${maintenanceData?.maintenance ? "text-orange-500" : "text-muted-foreground"}`} />
                  <p className="text-sm font-medium">
                    {maintenanceData?.maintenance ? "Maintenance mode is ON" : "App is live"}
                  </p>
                </div>
                <p className="text-xs text-muted-foreground">
                  {maintenanceData?.maintenance
                    ? "Users see a \"Comeback Later\" popup. Toggle off to restore access."
                    : "All users have normal access to the app."}
                </p>
              </div>
              <Switch
                data-testid="switch-maintenance-mode"
                checked={maintenanceData?.maintenance ?? false}
                disabled={maintenanceMutation.isPending}
                onCheckedChange={(v) => maintenanceMutation.mutate(v)}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Auto Hitter Card ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Target className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Auto Hitter</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Control how hit results from the Stripe Checkout Hitter appear in your Telegram group log. Admin DMs always receive the full site URL regardless of this setting.
          </p>
          {hitterSiteLoading ? (
            <div className="h-16 rounded-lg bg-muted animate-pulse" />
          ) : (
            <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border bg-muted/30">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Globe className="w-4 h-4 text-muted-foreground" />
                  <p className="text-sm font-medium">Show site URL in group log</p>
                </div>
                <p className="text-xs text-muted-foreground">
                  {hitterSiteData?.siteVisible
                    ? "The site URL is visible in group hit logs."
                    : "Group hit logs show \"Hidden From User\" instead of the site URL."}
                </p>
              </div>
              <Switch
                data-testid="switch-hitter-site-visible"
                checked={hitterSiteData?.siteVisible ?? true}
                disabled={hitterSiteMutation.isPending}
                onCheckedChange={(v) => hitterSiteMutation.mutate(v)}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Cloudflare Card ──────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Globe className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Cloudflare Protection</CardTitle>
          <Button size="icon" variant="ghost" className="ml-auto h-7 w-7" onClick={() => refetchCf()} data-testid="button-refresh-cf">
            <RefreshCw className="w-3.5 h-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Route your domain through Cloudflare for DDoS protection, WAF, and bot filtering. Enable <strong>CF-only mode</strong> to block any request that doesn't arrive via Cloudflare's edge network — direct-to-server attacks are rejected at the TCP layer.
          </p>

          {cfLoading ? (
            <div className="h-24 rounded-lg bg-muted animate-pulse" />
          ) : cfStatus ? (
            <div className="space-y-4">
              {/* Connection indicator */}
              <div className={`flex items-start gap-3 p-3 rounded-lg border ${
                cfStatus.viaCf
                  ? "bg-emerald-500/10 border-emerald-500/30"
                  : "bg-amber-500/10 border-amber-500/30"
              }`}>
                {cfStatus.viaCf
                  ? <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
                  : <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                }
                <div className="space-y-1 min-w-0">
                  <p className={`text-sm font-medium ${cfStatus.viaCf ? "text-emerald-400" : "text-amber-400"}`}>
                    {cfStatus.viaCf ? "You are connected via Cloudflare ✓" : "Not going through Cloudflare"}
                  </p>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span>Client IP: <code className="bg-muted px-1 rounded">{cfStatus.clientIp}</code></span>
                    {cfStatus.cfRay && <span>Ray: <code className="bg-muted px-1 rounded">{cfStatus.cfRay}</code></span>}
                    {cfStatus.cfCountry && <span>Country: <code className="bg-muted px-1 rounded">{cfStatus.cfCountry}</code></span>}
                  </div>
                  {!cfStatus.viaCf && (
                    <p className="text-xs text-amber-400/80 mt-1">
                      Point your domain's DNS to Cloudflare and enable proxy (orange cloud) to activate protection.
                    </p>
                  )}
                </div>
              </div>

              {/* CF-only toggle */}
              <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border bg-muted/30">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {cfStatus.cfOnly ? <Lock className="w-4 h-4 text-emerald-400" /> : <Unlock className="w-4 h-4 text-muted-foreground" />}
                    <p className="text-sm font-medium">CF-only mode</p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {cfStatus.cfOnly
                      ? "Direct connections are blocked in production. Only Cloudflare edge IPs can reach the server."
                      : "Direct connections are allowed. Enable to force all traffic through Cloudflare."}
                  </p>
                  {cfStatus.cfOnly && !cfStatus.viaCf && (
                    <p className="text-xs text-red-400 mt-1">
                      ⚠ CF-only is enabled but you're not going through Cloudflare — enabling this now would lock you out in production!
                    </p>
                  )}
                </div>
                <Switch
                  data-testid="switch-cf-only"
                  checked={cfStatus.cfOnly}
                  disabled={cfToggleMutation.isPending}
                  onCheckedChange={(v) => cfToggleMutation.mutate(v)}
                />
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Unable to fetch Cloudflare status.</p>
          )}
        </CardContent>
      </Card>

      {/* ── Webhook Card ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Webhook className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Telegram Webhook</CardTitle>
          <Button size="icon" variant="ghost" className="ml-auto h-7 w-7" onClick={() => refetchWebhook()} data-testid="button-refresh-webhook">
            <RefreshCw className="w-3.5 h-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Setting a webhook blocks <code className="text-xs bg-muted px-1 rounded">getUpdates</code> — which attackers use with a stolen bot token to spy on your messages. Once active, any call to <code className="text-xs bg-muted px-1 rounded">getUpdates</code> returns a 409 error.
          </p>

          {webhookLoading ? (
            <div className="h-16 rounded-lg bg-muted animate-pulse" />
          ) : webhookStatus ? (
            <div className="space-y-3">
              {/* Status indicator */}
              <div className={`flex items-center gap-3 p-3 rounded-lg border ${
                webhookStatus.ours
                  ? "bg-emerald-500/10 border-emerald-500/30"
                  : webhookStatus.active
                  ? "bg-amber-500/10 border-amber-500/30"
                  : "bg-muted/50 border-border"
              }`}>
                {webhookStatus.ours ? (
                  <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                ) : webhookStatus.active ? (
                  <ShieldOff className="w-5 h-5 text-amber-400 flex-shrink-0" />
                ) : (
                  <ShieldOff className="w-5 h-5 text-muted-foreground flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${
                    webhookStatus.ours ? "text-emerald-400" : webhookStatus.active ? "text-amber-400" : "text-muted-foreground"
                  }`}>
                    {webhookStatus.ours ? "Webhook Active — getUpdates blocked ✓" : webhookStatus.active ? "Webhook set to a different URL" : "No webhook — getUpdates is open"}
                  </p>
                  {webhookStatus.url && (
                    <p className="text-xs text-muted-foreground truncate" title={webhookStatus.url}>{webhookStatus.url}</p>
                  )}
                  {webhookStatus.lastError && (
                    <p className="text-xs text-red-400 mt-0.5">⚠ {webhookStatus.lastError}</p>
                  )}
                </div>
                {webhookStatus.pendingUpdateCount > 0 && (
                  <Badge variant="secondary" className="ml-auto flex-shrink-0">{webhookStatus.pendingUpdateCount} pending</Badge>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex gap-2">
                <Button
                  data-testid="button-webhook-setup"
                  onClick={() => setupWebhookMutation.mutate()}
                  disabled={setupWebhookMutation.isPending || webhookStatus.ours}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {setupWebhookMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <ShieldCheck className="w-4 h-4 mr-2" />}
                  {webhookStatus.ours ? "Already Active" : "Activate Webhook"}
                </Button>
                {webhookStatus.active && (
                  <Button
                    data-testid="button-webhook-remove"
                    variant="outline"
                    onClick={() => removeWebhookMutation.mutate()}
                    disabled={removeWebhookMutation.isPending}
                    className="flex-shrink-0"
                  >
                    {removeWebhookMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldOff className="w-4 h-4" />}
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Configure a bot token first to manage webhooks.</p>
          )}
        </CardContent>
      </Card>

      {/* ── Captcha Solver Keys ──────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Bot className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Captcha Solver</CardTitle>
          {captchaKeysSaved && (
            <Badge variant="secondary" className="ml-auto text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
              Saved
            </Badge>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            API keys for automatic captcha solving in the Auto Hitter and card checker. Supports <strong>hCaptcha</strong>, <strong>reCaptcha v2</strong>, and <strong>Cloudflare Turnstile</strong>. Keys are read live — no bot restart needed after saving.
          </p>

          <div className="space-y-3">
            {/* NopeCHA key */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">NopeCHA API Key</label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    type={showNopechaKey ? "text" : "password"}
                    value={nopechaKey}
                    onChange={(e) => setNopechaKey(e.target.value)}
                    placeholder="Enter your NopeCHA API key..."
                    className="pr-10 font-mono text-sm"
                    data-testid="input-nopecha-key"
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => setShowNopechaKey(v => !v)}
                  >
                    {showNopechaKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-xs"
                  onClick={() => window.open("https://nopecha.com/", "_blank")}
                >
                  Get Key
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Primary solver. Supports hCaptcha, reCaptcha, Turnstile. Used first when present.
              </p>
            </div>

            {/* CaptchaAI key (fallback) */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">CaptchaAI API Key <span className="normal-case">(fallback)</span></label>
              <Input
                type="password"
                value={captchaaiKey}
                onChange={(e) => setCaptchaaiKey(e.target.value)}
                placeholder="Optional fallback key..."
                className="font-mono text-sm"
                data-testid="input-captchaai-key"
              />
              <p className="text-xs text-muted-foreground">
                Used automatically if NopeCHA fails or is not set.
              </p>
            </div>

            <Button
              size="sm"
              disabled={saveCaptchaKeys.isPending}
              onClick={() => saveCaptchaKeys.mutate()}
              data-testid="button-save-captcha-keys"
            >
              {saveCaptchaKeys.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save Captcha Keys
            </Button>

            {/* Status indicator */}
            <div className={`flex items-center gap-2 p-2 rounded-lg text-xs border ${
              nopechaKey || captchaaiKey
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-amber-500/10 border-amber-500/30 text-amber-400"
            }`}>
              {nopechaKey || captchaaiKey
                ? <><CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" /> Captcha solving active</>
                : <><AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" /> No captcha key set — captchas will block the Auto Hitter</>
              }
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Logs Group Card ──────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Users className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Logs Group</CardTitle>
          {logsGroupSaved && (
            <Badge variant="secondary" className="ml-auto text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
              Saved
            </Badge>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A separate Telegram group where <strong>all check and hitter results</strong> are logged. Logs in this group are <strong>never auto-deleted</strong>. Users do <strong>not</strong> need to join this group — it is write-only for the bot.
          </p>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Logs Group ID</label>
            <Input
              type="text"
              value={logsGroupId}
              onChange={(e) => setLogsGroupId(e.target.value)}
              placeholder="e.g. -1001234567890"
              className="font-mono text-sm"
              data-testid="input-logs-group-id"
            />
            <p className="text-xs text-muted-foreground">
              Use a negative ID for supergroups (e.g. <code className="bg-muted px-1 py-0.5 rounded text-xs">-1001234567890</code>). Add the bot as an admin in this group first. This is separate from the force-join group.
            </p>
          </div>
          <Button
            size="sm"
            disabled={saveLogsConfig.isPending}
            onClick={() => saveLogsConfig.mutate()}
            data-testid="button-save-logs-group"
          >
            {saveLogsConfig.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
            Save Logs Group
          </Button>
        </CardContent>
      </Card>

      {/* ── Data Export Card ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Database className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Data Export</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Export all your bot data (users, keys, tiers, settings, etc.) as a single JSON snapshot file.
            Use this when moving to a new Replit — run <code className="bg-muted px-1 py-0.5 rounded text-xs">node scripts/import_data.js</code> on the new project to restore everything.
          </p>
          <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border bg-muted/30">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Download className="w-4 h-4 text-muted-foreground" />
                <p className="text-sm font-medium">Download data snapshot</p>
              </div>
              <p className="text-xs text-muted-foreground">
                Force-saves all live data to database then packages all 24 JSON files into one portable file.
              </p>
            </div>
            <Button
              data-testid="button-export-snapshot"
              size="sm"
              variant="outline"
              onClick={async () => {
                try {
                  const res = await fetch(apiUrl("/api/admin/export-snapshot"), {
                    method: "POST",
                    credentials: "include",
                  });
                  if (!res.ok) throw new Error("Export failed");
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `ogm_data_snapshot_${Date.now()}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (e: any) {
                  alert("Export failed: " + e.message);
                }
              }}
            >
              <Download className="w-4 h-4 mr-2" />
              Export
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
