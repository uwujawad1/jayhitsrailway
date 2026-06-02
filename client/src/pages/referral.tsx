import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, Copy, Check, Users, DollarSign, Gift, Crown,
  Star, TrendingUp, Clock, Wallet, Share2, ExternalLink, AlertCircle, CheckCircle2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { ThemeToggle } from "@/components/theme-toggle";

interface ReferralData {
  code: string;
  balance: number;
  totalEarned: number;
  referredCount: number;
  redeemedHistory: { plan: string; amount: number; redeemedAt: string }[];
}

interface MembershipData {
  member: boolean;
  status: string;
  groupLink?: string;
  channelLink?: string;
}

export default function ReferralPage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const [copiedLink, setCopiedLink] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [manualCode, setManualCode] = useState("");

  const { data, isLoading } = useQuery<ReferralData>({
    queryKey: ["/api/referral"],
  });

  const { data: membership, refetch: refetchMembership } = useQuery<MembershipData>({
    queryKey: ["/api/user/membership"],
    staleTime: 60000,
  });

  // Always build the link client-side so it matches the real domain
  const referralLink = data?.code
    ? `${window.location.origin}/?ref=${data.code}`
    : null;

  const applyMutation = useMutation({
    mutationFn: async (code: string) => {
      const res = await apiRequest("POST", "/api/referral/apply", { code });
      const json = await res.json();
      if (!res.ok) throw Object.assign(new Error(json.error || "Failed"), { data: json });
      return json;
    },
    onSuccess: () => {
      toast({ title: "Referral code applied!" });
      setManualCode("");
      queryClient.invalidateQueries({ queryKey: ["/api/referral"] });
    },
    onError: (err: any) => {
      const data = err?.data;
      if (data?.requiresMembership) {
        toast({ title: err.message, description: "Join the channel and group below first, then try again.", variant: "destructive" });
        refetchMembership();
      } else {
        toast({ title: err.message, variant: "destructive" });
      }
    },
  });

  const redeemMutation = useMutation({
    mutationFn: async (plan: string) => {
      const res = await apiRequest("POST", "/api/referral/redeem", { plan });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Redemption failed");
      return json;
    },
    onSuccess: (result) => {
      toast({ title: "Plan Activated!", description: result.message });
      queryClient.invalidateQueries({ queryKey: ["/api/referral"] });
      queryClient.invalidateQueries({ queryKey: ["/api/user/tier"] });
      queryClient.invalidateQueries({ queryKey: ["/api/user/dashboard"] });
    },
    onError: (err: Error) => {
      toast({ title: err.message, variant: "destructive" });
    },
  });

  const copyText = async (text: string, type: "link" | "code") => {
    try {
      await navigator.clipboard.writeText(text);
      if (type === "link") { setCopiedLink(true); setTimeout(() => setCopiedLink(false), 2000); }
      else { setCopiedCode(true); setTimeout(() => setCopiedCode(false), 2000); }
      toast({ title: "Copied!" });
    } catch {
      toast({ title: "Failed to copy", variant: "destructive" });
    }
  };

  const shareLink = () => {
    if (!referralLink) return;
    const text = `Join JayHits\n${referralLink}`;
    if (navigator.share) {
      navigator.share({ title: "JayHits", text, url: referralLink }).catch(() => {});
    } else {
      copyText(referralLink, "link");
    }
  };

  const balance = data?.balance ?? 0;
  const canRedeemSilver = balance >= 5;
  const canRedeemGold = balance >= 7;
  const needForSilver = Math.max(0, 5 - balance);
  const needForGold = Math.max(0, 7 - balance);
  const moreReferralsForSilver = Math.ceil(needForSilver / 0.30);
  const isMember = membership?.member ?? true;
  const groupLink = membership?.groupLink || "";
  const channelLink = membership?.channelLink || "";

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <header className="flex items-center justify-between gap-2 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back">
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <h1 className="text-base lg:text-xl font-semibold" data-testid="text-page-title">Referral & Earn</h1>
        </div>
        <ThemeToggle />
      </header>

      <main className="flex-1 p-3 lg:p-6 max-w-2xl mx-auto w-full flex flex-col gap-4">

        {/* Hero */}
        <div className="rounded-xl bg-gradient-to-br from-primary/20 via-primary/10 to-transparent border border-primary/20 p-4 lg:p-6">
          <div className="flex items-center gap-2 text-primary font-semibold text-xs mb-1">
            <Gift className="w-3.5 h-3.5" /> Earn by sharing
          </div>
          <h2 className="text-lg lg:text-2xl font-bold mb-1">Get $0.30 per referral</h2>
          <p className="text-xs lg:text-sm text-muted-foreground">
            Share your link. Every new user earns you <span className="font-semibold text-foreground">$0.30</span>.
            Collect <span className="font-semibold text-foreground">$5</span> → Silver&nbsp;·&nbsp;<span className="font-semibold text-foreground">$7</span> → Gold (7 days each)
          </p>
        </div>

        {/* Membership Requirement */}
        <Card className={`border ${isMember ? "border-green-500/30 bg-green-500/5" : "border-orange-500/30 bg-orange-500/5"}`} data-testid="card-membership-requirement">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              {isMember ? (
                <CheckCircle2 className="w-5 h-5 text-green-500 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="w-5 h-5 text-orange-500 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-sm mb-0.5">
                  {isMember ? "You're eligible to earn rewards" : "Join required to earn rewards"}
                </p>
                <p className="text-xs text-muted-foreground mb-3">
                  {isMember
                    ? "You are a member of the channel and group. Your referrals will be credited."
                    : "You must join both our Telegram channel and group before your referrals count."}
                </p>
                {!isMember && (groupLink || channelLink) && (
                  <div className="flex flex-col sm:flex-row gap-2">
                    {channelLink && (
                      <a href={channelLink} target="_blank" rel="noopener noreferrer" data-testid="link-join-channel">
                        <Button size="sm" variant="outline" className="w-full sm:w-auto gap-1.5 text-xs border-orange-500/40 hover:bg-orange-500/10">
                          Join Channel <ExternalLink className="w-3 h-3" />
                        </Button>
                      </a>
                    )}
                    {groupLink && (
                      <a href={groupLink} target="_blank" rel="noopener noreferrer" data-testid="link-join-group">
                        <Button size="sm" variant="outline" className="w-full sm:w-auto gap-1.5 text-xs border-orange-500/40 hover:bg-orange-500/10">
                          Join Group <ExternalLink className="w-3 h-3" />
                        </Button>
                      </a>
                    )}
                    <Button size="sm" variant="ghost" className="text-xs text-muted-foreground" onClick={() => refetchMembership()} data-testid="button-recheck-membership">
                      Check Again
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Manual Apply Code */}
        {!data?.referredCount && (
          <Card data-testid="card-apply-code">
            <CardHeader className="pb-2 pt-4 px-4">
              <CardTitle className="text-sm flex items-center gap-2">
                <Gift className="w-4 h-4" /> Apply a Referral Code
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <p className="text-xs text-muted-foreground mb-3">
                Got referred by a friend? Enter their code to credit them $0.30. Requires channel + group membership.
              </p>
              <div className="flex gap-2">
                <Input
                  placeholder="REF1234567890"
                  value={manualCode}
                  onChange={e => setManualCode(e.target.value.toUpperCase())}
                  className="font-mono text-sm"
                  data-testid="input-referral-code"
                />
                <Button
                  onClick={() => applyMutation.mutate(manualCode.trim())}
                  disabled={applyMutation.isPending || !manualCode.trim() || !/^REF\d{5,15}$/.test(manualCode.trim())}
                  size="sm"
                  data-testid="button-apply-code"
                >
                  {applyMutation.isPending ? "Applying…" : "Apply"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Stats */}
        <div className="grid grid-cols-3 gap-2 lg:gap-3">
          <Card data-testid="card-stat-balance">
            <CardContent className="pt-3 pb-3 flex flex-col items-center gap-0.5 text-center px-2">
              <Wallet className="w-4 h-4 text-primary mb-1" />
              <span className="text-lg lg:text-2xl font-bold text-primary leading-none" data-testid="text-balance">
                ${balance.toFixed(2)}
              </span>
              <span className="text-[10px] lg:text-xs text-muted-foreground">Balance</span>
            </CardContent>
          </Card>
          <Card data-testid="card-stat-referred">
            <CardContent className="pt-3 pb-3 flex flex-col items-center gap-0.5 text-center px-2">
              <Users className="w-4 h-4 text-blue-400 mb-1" />
              <span className="text-lg lg:text-2xl font-bold leading-none" data-testid="text-referred-count">
                {data?.referredCount ?? 0}
              </span>
              <span className="text-[10px] lg:text-xs text-muted-foreground">Referred</span>
            </CardContent>
          </Card>
          <Card data-testid="card-stat-total">
            <CardContent className="pt-3 pb-3 flex flex-col items-center gap-0.5 text-center px-2">
              <TrendingUp className="w-4 h-4 text-green-400 mb-1" />
              <span className="text-lg lg:text-2xl font-bold text-green-400 leading-none" data-testid="text-total-earned">
                ${(data?.totalEarned ?? 0).toFixed(2)}
              </span>
              <span className="text-[10px] lg:text-xs text-muted-foreground">Total Earned</span>
            </CardContent>
          </Card>
        </div>

        {/* Referral Link */}
        <Card>
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <Share2 className="w-4 h-4" /> Your Referral Code
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 flex flex-col gap-3">

            {/* Code display — big and clean, no domain shown */}
            <div
              className="flex items-center justify-between gap-3 p-4 rounded-xl bg-primary/10 border border-primary/25 cursor-pointer"
              onClick={() => referralLink && copyText(referralLink, "link")}
              data-testid="text-referral-link"
            >
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Your Code</span>
                <span className="text-xl font-bold font-mono tracking-widest text-primary" data-testid="text-referral-code">
                  {isLoading ? "Loading..." : (data?.code ?? "—")}
                </span>
                <span className="text-[10px] text-muted-foreground">Tap to copy invite link</span>
              </div>
              <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/20 shrink-0">
                {copiedLink
                  ? <Check className="w-5 h-5 text-green-400" />
                  : <Copy className="w-5 h-5 text-primary" />}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex flex-col sm:flex-row gap-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => referralLink && copyText(referralLink, "link")}
                disabled={isLoading || !referralLink}
                data-testid="button-copy-link"
              >
                {copiedLink ? <Check className="w-3.5 h-3.5 mr-1.5 text-green-400" /> : <Copy className="w-3.5 h-3.5 mr-1.5" />}
                {copiedLink ? "Copied!" : "Copy Link"}
              </Button>
              <Button
                className="flex-1"
                onClick={shareLink}
                disabled={isLoading || !referralLink}
                data-testid="button-share-link"
              >
                <Share2 className="w-3.5 h-3.5 mr-1.5" />
                Share
              </Button>
            </div>

          </CardContent>
        </Card>

        {/* Redeem Balance */}
        <Card>
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <Wallet className="w-4 h-4" /> Redeem Balance
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 flex flex-col gap-4">
            <p className="text-xs text-muted-foreground">
              Use your referral balance to activate a plan instantly — no payment needed.
            </p>

            {/* Silver progress */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-gray-300 font-medium">
                  <Star className="w-3.5 h-3.5" /> Silver — $5.00 / 7 days
                </span>
                <span className="text-muted-foreground tabular-nums">${Math.min(balance, 5).toFixed(2)} / $5.00</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-gray-300 transition-all duration-700"
                  style={{ width: `${Math.min((balance / 5) * 100, 100)}%` }}
                  data-testid="progress-silver"
                />
              </div>
            </div>

            {/* Gold progress */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-amber-400 font-medium">
                  <Crown className="w-3.5 h-3.5" /> Gold — $7.00 / 7 days
                </span>
                <span className="text-muted-foreground tabular-nums">${Math.min(balance, 7).toFixed(2)} / $7.00</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-amber-400 transition-all duration-700"
                  style={{ width: `${Math.min((balance / 7) * 100, 100)}%` }}
                  data-testid="progress-gold"
                />
              </div>
            </div>

            {/* Redeem buttons — stacked on mobile, side-by-side on sm+ */}
            <div className="flex flex-col sm:flex-row gap-3">
              {/* Silver */}
              <div className="flex-1 flex flex-col gap-1">
                <Button
                  variant="outline"
                  className="w-full border-gray-400/40 hover:border-gray-300 disabled:opacity-50"
                  disabled={!canRedeemSilver || redeemMutation.isPending}
                  onClick={() => redeemMutation.mutate("silver")}
                  data-testid="button-redeem-silver"
                >
                  <Star className="w-4 h-4 mr-2 text-gray-300" />
                  Silver Plan — $5.00
                </Button>
                {!canRedeemSilver && (
                  <p className="text-[10px] text-center text-muted-foreground">
                    Need ${needForSilver.toFixed(2)} more ({moreReferralsForSilver} referral{moreReferralsForSilver !== 1 ? "s" : ""})
                  </p>
                )}
              </div>

              {/* Gold */}
              <div className="flex-1 flex flex-col gap-1">
                <Button
                  className="w-full bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50"
                  disabled={!canRedeemGold || redeemMutation.isPending}
                  onClick={() => redeemMutation.mutate("gold")}
                  data-testid="button-redeem-gold"
                >
                  <Crown className="w-4 h-4 mr-2" />
                  Gold Plan — $7.00
                </Button>
                {!canRedeemGold && (
                  <p className="text-[10px] text-center text-muted-foreground">
                    Need ${needForGold.toFixed(2)} more ({Math.ceil(needForGold / 0.4)} referral{Math.ceil(needForGold / 0.4) !== 1 ? "s" : ""})
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Redemption History */}
        {(data?.redeemedHistory?.length ?? 0) > 0 && (
          <Card>
            <CardHeader className="pb-2 pt-4 px-4">
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock className="w-4 h-4" /> Redemption History
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <div className="flex flex-col gap-2">
                {data!.redeemedHistory.map((h, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between text-sm p-2.5 rounded-lg bg-muted/50"
                    data-testid={`row-redemption-${i}`}
                  >
                    <div className="flex items-center gap-2">
                      {h.plan === "gold"
                        ? <Crown className="w-3.5 h-3.5 text-amber-400" />
                        : <Star className="w-3.5 h-3.5 text-gray-300" />}
                      <span className="capitalize font-medium text-sm">{h.plan} Plan</span>
                      <Badge variant="secondary" className="text-[10px]">7 days</Badge>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-red-400 font-medium">-${h.amount.toFixed(2)}</span>
                      <span className="text-muted-foreground">{new Date(h.redeemedAt).toLocaleDateString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* How it works */}
        <Card>
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <DollarSign className="w-4 h-4" /> How It Works
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="flex flex-col gap-3">
              {[
                { step: "1", text: "Join our Telegram Channel and Group (required)" },
                { step: "2", text: "Copy your referral link and share it with friends" },
                { step: "3", text: "Friend joins the channel & group, then applies your code" },
                { step: "4", text: "You instantly earn $0.30 per new user" },
                { step: "5", text: "Collect $5 → Silver or $7 → Gold (7 days each)" },
              ].map(({ step, text }) => (
                <div key={step} className="flex items-start gap-3 text-sm">
                  <span className="bg-primary/20 text-primary rounded-full w-5 h-5 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">
                    {step}
                  </span>
                  <span className="text-muted-foreground text-xs lg:text-sm">{text}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

      </main>
    </div>
  );
}
