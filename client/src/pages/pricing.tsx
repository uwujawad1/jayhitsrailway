import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Check, X, ArrowLeft, Crown, Star, Zap, Shield,
  CreditCard, ShoppingCart, Target, Search, Users, Cpu,
  ExternalLink, KeyRound, Sparkles, Gift,
} from "lucide-react";
import { PageTransition, StaggerContainer, StaggerItem } from "@/components/page-transition";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";

interface TierInfo {
  tier: string;
  limits: {
    dailyChecks: number;
    maxBatchCards: number;
    dailyShopifyChecks: number;
    massAccountMax: number;
    dailyFindsiteSearches: number;
    parallelWorkers: number;
    dailyHitterHits: number;
  };
  usage: {
    checks: number;
    shopifyChecks: number;
    findsiteSearches: number;
    accountMassChecks: number;
    hitterHits: number;
  };
}

interface PlanFeature {
  label: string;
  free: string;
  silver: string;
  gold: string;
  icon: typeof CreditCard;
}

const features: PlanFeature[] = [
  { label: "Daily CC Checks", free: "500", silver: "5,000", gold: "Unlimited", icon: CreditCard },
  { label: "Mass Check (Batch)", free: "50 cards", silver: "1,000 cards", gold: "5,000 cards", icon: Cpu },
  { label: "Auto Hitter", free: "2 Hits/Day", silver: "Unlimited", gold: "Unlimited", icon: Target },
  { label: "Auto Shopify (Daily)", free: "1,000", silver: "10,000", gold: "Unlimited", icon: ShoppingCart },
  { label: "Account Checker", free: "Single Only", silver: "Mass 500", gold: "Mass 1,000", icon: Users },
  { label: "Gateway Finder", free: "Not Available", silver: "3/day", gold: "10/day", icon: Search },
  { label: "Sites / Proxy / SK", free: "Unlimited", silver: "Unlimited", gold: "Unlimited", icon: Shield },
  { label: "Parallel Workers", free: "1", silver: "3", gold: "5", icon: Zap },
];

function getTierColor(tier: string) {
  switch (tier) {
    case "gold": return "text-amber-400";
    case "silver": return "text-gray-300";
    default: return "text-blue-400";
  }
}

function getTierBg(tier: string) {
  switch (tier) {
    case "gold": return "border-amber-500/40 bg-gradient-to-b from-amber-500/10 to-amber-500/5";
    case "silver": return "border-gray-400/40 bg-gradient-to-b from-gray-400/10 to-gray-400/5";
    default: return "border-blue-500/30 bg-gradient-to-b from-blue-500/5 to-transparent";
  }
}

function getTierIcon(tier: string) {
  switch (tier) {
    case "gold": return <Crown className="w-6 h-6 lg:w-7 lg:h-7 text-amber-400 transition-transform duration-300 hover:scale-110" />;
    case "silver": return <Star className="w-6 h-6 lg:w-7 lg:h-7 text-gray-300 transition-transform duration-300 hover:scale-110" />;
    default: return <Zap className="w-6 h-6 lg:w-7 lg:h-7 text-blue-400 transition-transform duration-300 hover:scale-110" />;
  }
}

const ADMIN_TELEGRAM = import.meta.env.VITE_ADMIN_TELEGRAM_USERNAME || "JayHitsAdmin";

export default function PricingPage() {
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const [redeemKey, setRedeemKey] = useState("");

  const { data: tierInfo } = useQuery<TierInfo>({
    queryKey: ["/api/user/tier"],
  });

  const redeemMutation = useMutation({
    mutationFn: async (key: string) => {
      const res = await apiRequest("POST", "/api/redeem", { key });
      return res.json();
    },
    onSuccess: (data) => {
      toast({
        title: "Plan Activated!",
        description: data.message || "Your plan has been activated successfully.",
      });
      setRedeemKey("");
      queryClient.invalidateQueries({ queryKey: ["/api/user/tier"] });
      queryClient.invalidateQueries({ queryKey: ["/api/user/dashboard"] });
    },
    onError: (err: any) => {
      toast({
        title: "Redemption Failed",
        description: err.message || "Invalid or expired key.",
        variant: "destructive",
      });
    },
  });

  const currentTier = tierInfo?.tier || "free";

  const plans = [
    { key: "free", name: "Free", tagline: "Get started", price: null, period: null, features: features.map(f => f.free) },
    { key: "silver", name: "Silver", tagline: "Most Popular", price: "$5", period: "7 days", features: features.map(f => f.silver) },
    { key: "gold", name: "Gold", tagline: "Best Value", price: "$7", period: "7 days", features: features.map(f => f.gold) },
  ];

  const handleBuyNow = (plan: string) => {
    const planName = plan.charAt(0).toUpperCase() + plan.slice(1);
    const message = encodeURIComponent(`Hey, I want to buy ${planName} Plan for 7 days`);
    window.open(`https://t.me/${ADMIN_TELEGRAM}?text=${message}`, "_blank");
  };

  const handleRedeem = () => {
    const key = redeemKey.trim();
    if (!key) {
      toast({ title: "Enter a key", description: "Please enter your redemption code.", variant: "destructive" });
      return;
    }
    redeemMutation.mutate(key);
  };

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <header className="flex items-center gap-3 p-3 lg:p-4 border-b sticky top-0 z-50 bg-background">
        <Button variant="ghost" size="icon" onClick={() => navigate("/")} data-testid="button-back" className="transition-all duration-300">
          <ArrowLeft className="w-5 h-5 lg:w-6 lg:h-6" />
        </Button>
        <h1 className="text-lg lg:text-xl font-semibold" data-testid="text-page-title">Plans & Pricing</h1>
      </header>

      <PageTransition className="flex-1 p-4 md:p-6 lg:p-8">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-8 lg:mb-10">
            <h2 className="text-2xl md:text-3xl lg:text-4xl font-bold mb-2 lg:mb-3">Choose Your Plan</h2>
            <p className="text-muted-foreground text-sm lg:text-base">Upgrade to unlock more power and higher limits</p>
          </div>

          <StaggerContainer className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 lg:gap-8 mb-8 lg:mb-10">
            {plans.map((plan, planIdx) => {
              const isCurrentPlan = currentTier === plan.key;
              const isPopular = plan.key === "silver";
              const isBest = plan.key === "gold";

              return (
                <StaggerItem key={plan.key}>
                <Card
                  className={`relative overflow-hidden transition-all duration-300 hover:scale-[1.02] hover:shadow-lg ${getTierBg(plan.key)} ${isCurrentPlan ? "ring-2 ring-primary" : ""}`}
                  data-testid={`card-plan-${plan.key}`}
                >
                  {(isPopular || isBest) && (
                    <div className={`absolute top-0 right-0 px-3 py-1 text-xs lg:text-sm font-bold rounded-bl-lg ${isPopular ? "bg-gray-400/20 text-gray-300" : "bg-amber-500/20 text-amber-400"}`}>
                      {plan.tagline}
                    </div>
                  )}

                  <CardHeader className="pb-3 lg:pb-4 pt-6 lg:pt-8">
                    <div className="flex items-center gap-3 mb-2 lg:mb-3">
                      {getTierIcon(plan.key)}
                      <CardTitle className={`text-xl lg:text-2xl ${getTierColor(plan.key)}`}>{plan.name}</CardTitle>
                    </div>

                    {plan.price ? (
                      <div className="flex items-baseline gap-1 mb-1 lg:mb-2">
                        <span className={`text-3xl lg:text-4xl font-bold ${getTierColor(plan.key)}`}>{plan.price}</span>
                        <span className="text-sm lg:text-base text-muted-foreground">/ {plan.period}</span>
                      </div>
                    ) : (
                      <div className="flex items-baseline gap-1 mb-1 lg:mb-2">
                        <span className="text-3xl lg:text-4xl font-bold text-blue-400">Free</span>
                        <span className="text-sm lg:text-base text-muted-foreground">forever</span>
                      </div>
                    )}

                    {isCurrentPlan && (
                      <Badge className="w-fit bg-primary/20 text-primary border-primary/30 lg:text-sm lg:px-3 lg:py-1" data-testid={`badge-current-${plan.key}`}>
                        Current Plan
                      </Badge>
                    )}
                  </CardHeader>

                  <CardContent className="pt-0 lg:pb-8">
                    <div className="flex flex-col gap-2.5 lg:gap-3">
                      {features.map((feature, i) => {
                        const value = plan.features[i];
                        const isUnavailable = value === "Not Available";
                        const isUnlimited = value === "Unlimited";

                        return (
                          <div
                            key={feature.label}
                            className={`flex items-center gap-2 text-sm lg:text-base ${isUnavailable ? "opacity-40" : ""}`}
                            data-testid={`feature-${plan.key}-${i}`}
                          >
                            {isUnavailable ? (
                              <X className="w-4 h-4 lg:w-5 lg:h-5 text-red-400 shrink-0" />
                            ) : (
                              <Check className={`w-4 h-4 lg:w-5 lg:h-5 shrink-0 ${isUnlimited ? "text-emerald-400" : "text-primary"}`} />
                            )}
                            <span className="flex-1 text-muted-foreground">{feature.label}</span>
                            <span className={`font-medium ${isUnlimited ? "text-emerald-400" : ""}`}>{value}</span>
                          </div>
                        );
                      })}
                    </div>

                    {plan.key !== "free" && (
                      <div className="mt-4 lg:mt-6 flex flex-col gap-2 lg:gap-3">
                        <div className={`flex items-center gap-2 p-2 lg:p-3 rounded-md ${plan.key === "silver" ? "bg-gray-400/10 border border-gray-400/20" : "bg-amber-500/10 border border-amber-500/20"}`}>
                          <Shield className={`w-4 h-4 lg:w-5 lg:h-5 ${plan.key === "silver" ? "text-gray-300" : "text-amber-400"}`} />
                          <span className={`text-xs lg:text-sm ${plan.key === "silver" ? "text-gray-300" : "text-amber-400"}`}>Priority Support</span>
                        </div>

                        <Button
                          className={`w-full mt-1 font-semibold transition-all duration-300 lg:text-base lg:py-5 ${plan.key === "gold" ? "bg-amber-500 hover:bg-amber-600 text-black" : "bg-gray-500 hover:bg-gray-600 text-white"}`}
                          onClick={() => handleBuyNow(plan.key)}
                          data-testid={`button-buy-${plan.key}`}
                        >
                          <ExternalLink className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                          Buy Now — {plan.price}
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
                </StaggerItem>
              );
            })}
          </StaggerContainer>

          <Card className="mb-6 lg:mb-8 border-primary/30 bg-gradient-to-r from-primary/5 to-transparent animate-fade-in-up" data-testid="card-redeem">
            <CardHeader className="pb-3 lg:pb-4 p-4 lg:p-6">
              <div className="flex items-center gap-3">
                <div className="p-2 lg:p-3 rounded-lg bg-primary/10 transition-transform duration-300 hover:scale-110">
                  <Gift className="w-5 h-5 lg:w-6 lg:h-6 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-base lg:text-lg">Redeem Code</CardTitle>
                  <p className="text-xs lg:text-sm text-muted-foreground mt-0.5">Have a redemption key? Enter it below to activate your plan</p>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0 p-4 lg:p-6 lg:pt-0">
              <div className="flex gap-2 lg:gap-3">
                <div className="relative flex-1">
                  <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 lg:w-5 lg:h-5 text-muted-foreground" />
                  <Input
                    placeholder="Enter your redemption key"
                    value={redeemKey}
                    onChange={(e) => setRedeemKey(e.target.value.toUpperCase())}
                    className="pl-10 lg:pl-12 font-mono tracking-wider uppercase lg:text-sm lg:py-5"
                    onKeyDown={(e) => e.key === "Enter" && handleRedeem()}
                    data-testid="input-redeem-key"
                  />
                </div>
                <Button
                  onClick={handleRedeem}
                  disabled={redeemMutation.isPending || !redeemKey.trim()}
                  className="px-6 lg:px-8 transition-all duration-300 lg:text-sm lg:py-5"
                  data-testid="button-redeem"
                >
                  {redeemMutation.isPending ? (
                    <Sparkles className="w-4 h-4 lg:w-5 lg:h-5 animate-spin" />
                  ) : (
                    <>
                      <Gift className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                      Redeem
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="text-center">
            <p className="text-sm lg:text-base text-muted-foreground mb-1">
              Click "Buy Now" to contact admin on Telegram for payment
            </p>
            <p className="text-xs lg:text-sm text-muted-foreground mb-3">
              After payment, you'll receive a redemption key to activate your plan
            </p>
          </div>
        </div>
      </PageTransition>
    </div>
  );
}
