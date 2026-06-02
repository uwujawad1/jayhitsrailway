import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Users, Zap, Trophy, Shield, Crown, Star,
  Loader2, TrendingUp, CreditCard, Sparkles, Search, Target,
  Filter, ShoppingCart, GraduationCap, Settings, Menu,
  ShieldEllipsis, LogOut, User, UserCheck, Tv, Gamepad2, BookOpen,
  ArrowUpRight, Tag, Scan, Gift
} from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { PageTransition, StaggerContainer, StaggerItem } from "@/components/page-transition";
import { useAuth } from "@/lib/auth";
import { useState } from "react";
import { useToast } from "@/hooks/use-toast";

interface DashboardData {
  totalUsers: number;
  totalHits: number;
  userHits: number;
  userRank: number;
  userRole: string;
  premiumExpiry: string | null;
  tier: string;
  tierLimits: {
    dailyChecks: number;
    maxBatchCards: number;
    dailyShopifyChecks: number;
    massAccountMax: number;
    dailyFindsiteSearches: number;
    parallelWorkers: number;
  };
  dailyUsage: {
    checks: number;
    shopifyChecks: number;
    findsiteSearches: number;
    accountMassChecks: number;
  };
}

function getTierBadge(tier: string) {
  switch (tier) {
    case "gold":
      return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 lg:text-sm lg:px-3 lg:py-1" data-testid="badge-tier"><Crown className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />Gold</Badge>;
    case "silver":
      return <Badge className="bg-gray-300/20 text-gray-300 border-gray-400/30 lg:text-sm lg:px-3 lg:py-1" data-testid="badge-tier"><Star className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />Silver</Badge>;
    default:
      return <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30 lg:text-sm lg:px-3 lg:py-1" data-testid="badge-tier"><Zap className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />Free</Badge>;
  }
}

function getRoleBadge(role: string) {
  switch (role) {
    case "Admin":
      return <Badge className="bg-red-500/20 text-red-400 border-red-500/30 lg:text-sm lg:px-3 lg:py-1" data-testid="badge-role"><Shield className="w-3 h-3 lg:w-4 lg:h-4 mr-1" />Admin</Badge>;
    default:
      return null;
  }
}

function formatLimit(value: number): string {
  if (value === -1) return "\u221E";
  if (value >= 1000) return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`;
  return String(value);
}

const BASE_QUICK_TOOLS = [
  { label: "C-C Checker", icon: CreditCard, path: "/checker", color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20 hover:bg-blue-500/20" },
  { label: "Auto Hitter", icon: Target, path: "/autohitter", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20 hover:bg-emerald-500/20" },
  { label: "CC Generator", icon: Sparkles, path: "/generator", color: "text-purple-400", bg: "bg-purple-500/10 border-purple-500/20 hover:bg-purple-500/20" },
  { label: "Gateway Finder", icon: Search, path: "/finder", color: "text-cyan-400", bg: "bg-cyan-500/10 border-cyan-500/20 hover:bg-cyan-500/20" },
  { label: "CC Filter", icon: Filter, path: "/filter", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20 hover:bg-amber-500/20" },
  { label: "Auto Shopify", icon: ShoppingCart, path: "/shopify", color: "text-green-400", bg: "bg-green-500/10 border-green-500/20 hover:bg-green-500/20" },
  { label: "Skool Gate", icon: GraduationCap, path: "/skool", color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20 hover:bg-orange-500/20" },
  { label: "Accounts Checker", icon: UserCheck, path: "/accounts", color: "text-rose-400", bg: "bg-rose-500/10 border-rose-500/20 hover:bg-rose-500/20" },
  { label: "SK/CC Scraper", icon: Scan, path: "/scraper", color: "text-pink-400", bg: "bg-pink-500/10 border-pink-500/20 hover:bg-pink-500/20" },
  { label: "Settings", icon: Settings, path: "/user-settings", color: "text-gray-400", bg: "bg-gray-500/10 border-gray-500/20 hover:bg-gray-500/20" },
];

const ACCOUNT_CHECKERS_MENU = [
  { id: "crunchyroll", label: "Crunchyroll Checker", icon: Tv, path: "/accounts?checker=crunchyroll", testId: "button-crunchyroll-checker" },
  { id: "xbox", label: "Xbox Checker", icon: Gamepad2, path: "/accounts?checker=xbox", testId: "button-xbox-checker" },
  { id: "cyberghost", label: "CyberGhost Checker", icon: Shield, path: "/accounts?checker=cyberghost", testId: "button-cyberghost-checker" },
  { id: "duolingo", label: "Duolingo Checker", icon: BookOpen, path: "/accounts?checker=duolingo", testId: "button-duolingo-checker" },
  { id: "hoichoi", label: "Hoichoi Checker", icon: Tv, path: "/accounts?checker=hoichoi", testId: "button-hoichoi-checker" },
];

export default function UserDashboardPage() {
  const [, navigate] = useLocation();
  const { user, isAdmin, logout } = useAuth();
  const { toast } = useToast();
  const [menuOpen, setMenuOpen] = useState(false);

  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ["/api/user/dashboard"],
    refetchInterval: 30000,
  });

  const { data: checkerStatuses } = useQuery<Record<string, boolean>>({
    queryKey: ["/api/account-checkers/status"],
  });

  const displayName = [user?.firstName, user?.lastName].filter(Boolean).join(" ") || user?.username || `ID: ${user?.userId}`;
  const tier = data?.tier || "free";
  const tierLimits = data?.tierLimits;
  const usage = data?.dailyUsage;
  const isPaidUser = tier === "silver" || tier === "gold";

  const quickTools = [...BASE_QUICK_TOOLS];

  return (
    <div className="app-shell flex flex-col min-h-screen">
      <header className="app-topbar">
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
                  {user?.photoUrl ? (
                    <Avatar className="w-8 h-8" data-testid="img-avatar-sidebar">
                      <AvatarImage src={user.photoUrl} alt={displayName} />
                      <AvatarFallback><User className="w-4 h-4" /></AvatarFallback>
                    </Avatar>
                  ) : (
                    <User className="w-4 h-4 text-muted-foreground" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium" data-testid="text-user-name">{displayName}</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      {getTierBadge(tier)}
                      {isAdmin && getRoleBadge("Admin")}
                    </div>
                  </div>
                </div>

                <Button variant="ghost" className="w-full justify-start gap-2 bg-primary/10" onClick={() => { setMenuOpen(false); navigate("/"); }} data-testid="button-dashboard">
                  <TrendingUp className="w-4 h-4" />
                  Dashboard
                </Button>

                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/pricing"); }} data-testid="button-pricing">
                  <Tag className="w-4 h-4" />
                  Plans & Pricing
                </Button>

                <Button variant="ghost" className="w-full justify-start gap-2 text-primary" onClick={() => { setMenuOpen(false); navigate("/referral"); }} data-testid="button-referral">
                  <Gift className="w-4 h-4" />
                  Referral & Earn
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
                <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate("/scraper"); }} data-testid="button-scraper">
                  <Scan className="w-4 h-4" />
                  SK/CC Scraper
                </Button>

                {ACCOUNT_CHECKERS_MENU.filter(c => !checkerStatuses || checkerStatuses[c.id] !== false).length > 0 && (
                  <div className="text-xs text-muted-foreground font-semibold mt-2 mb-1 px-1">Account Checkers</div>
                )}

                {ACCOUNT_CHECKERS_MENU.filter(c => !checkerStatuses || checkerStatuses[c.id] !== false).map(checker => (
                  <Button key={checker.id} variant="ghost" className="w-full justify-start gap-2" onClick={() => { setMenuOpen(false); navigate(checker.path); }} data-testid={checker.testId}>
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
          <div className="app-topbar__title">
            <div className="app-topbar__icon">
              <TrendingUp className="w-5 h-5 lg:w-6 lg:h-6 text-primary" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary/80">Workspace</p>
              <h1 className="text-lg font-semibold lg:text-xl" data-testid="text-page-title">Dashboard</h1>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <Button variant="ghost" size="icon" onClick={() => navigate("/admin")} data-testid="button-admin-header" title="Admin Panel">
              <ShieldEllipsis className="w-4 h-4" />
            </Button>
          )}
          <div className="app-chip">Live Console</div>
        </div>
      </header>

      <PageTransition className="app-page flex-1">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin text-primary" />
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 lg:gap-6">
            <Card className="animate-fade-in-up overflow-hidden">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <span className="lg:text-xl">🏆</span>
                  Your Status
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3">
                <div className="flex items-center gap-3 lg:gap-5 mb-4 rounded-lg border border-white/8 bg-white/[0.03] p-3 lg:p-5 transition-all duration-300 hover:bg-white/[0.05]">
                  {user?.photoUrl ? (
                    <Avatar className="w-12 h-12 lg:w-16 lg:h-16 border border-primary/30" data-testid="img-avatar-status">
                      <AvatarImage src={user.photoUrl} alt={displayName} />
                      <AvatarFallback className="bg-primary/20 text-xl lg:text-3xl font-bold text-primary">
                        {displayName.charAt(0).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                  ) : (
                    <div className="flex items-center justify-center w-12 h-12 lg:w-16 lg:h-16 rounded-full bg-primary/20 border border-primary/30">
                      <span className="text-xl lg:text-3xl font-bold text-primary">
                        {displayName.charAt(0).toUpperCase()}
                      </span>
                    </div>
                  )}
                  <div className="flex-1">
                    <p className="font-semibold text-base lg:text-xl" data-testid="text-display-name">{displayName}</p>
                    <div className="flex items-center gap-2 mt-1 lg:mt-2 flex-wrap">
                      {getTierBadge(tier)}
                      {isAdmin && getRoleBadge("Admin")}
                      <Badge variant="outline" className="text-[10px] lg:text-xs lg:px-2.5 lg:py-0.5">Rank #{data?.userRank || "-"}</Badge>
                      {data?.premiumExpiry && (
                        <span className="text-[10px] lg:text-xs text-muted-foreground">
                          Expires: {new Date(data.premiumExpiry).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-4 gap-3 lg:gap-5">
              {[
                { icon: "👥", value: data?.totalUsers || 0, label: "Total Users", color: "", testId: "text-total-users", delay: "0ms" },
                { icon: "⚡", value: data?.totalHits || 0, label: "Total Hits", color: "text-emerald-400", testId: "text-total-hits", delay: "50ms" },
                { icon: "🎯", value: data?.userHits || 0, label: "Your Hits", color: "text-purple-400", testId: "text-user-hits", delay: "100ms" },
                { icon: "🏆", value: `#${data?.userRank || "-"}`, label: "Your Rank", color: "text-amber-400", testId: "text-user-rank", delay: "150ms" },
              ].map((stat) => (
                <Card key={stat.testId} className="metric-panel p-3 lg:p-5 border animate-fade-in-up transition-all duration-300 hover:-translate-y-1 hover:shadow-lg" style={{ animationDelay: stat.delay }}>
                  <div className="flex flex-col items-center gap-1.5 lg:gap-3">
                    <span className="text-xl lg:text-3xl">{stat.icon}</span>
                    <p className={`text-2xl lg:text-4xl font-bold ${stat.color} animate-count-up`} data-testid={stat.testId}>{stat.value}</p>
                    <p className="text-[10px] lg:text-sm text-muted-foreground">{stat.label}</p>
                  </div>
                </Card>
              ))}
            </div>

            {/* Referral Teaser */}
            <Card
              className="animate-fade-in-up cursor-pointer border-primary/10 bg-[linear-gradient(135deg,rgba(84,214,165,0.14),rgba(255,255,255,0.02))] transition-shadow hover:shadow-lg"
              style={{ animationDelay: "170ms" }}
              onClick={() => navigate("/referral")}
              data-testid="card-referral-teaser"
            >
              <CardContent className="p-3 lg:p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/20 shrink-0">
                    <Gift className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold">Earn with Referrals</p>
                    <p className="text-xs text-muted-foreground">Get $0.40 per friend — redeem for Silver ($5) or Gold ($7) plan</p>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-primary shrink-0" />
              </CardContent>
            </Card>

            {tierLimits && usage && (
              <Card className="animate-fade-in-up" style={{ animationDelay: "180ms" }}>
                <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                      <span className="lg:text-xl">📊</span>
                      Daily Usage
                    </CardTitle>
                    {tier !== "gold" && (
                      <Button variant="ghost" size="sm" className="h-6 lg:h-8 text-xs lg:text-sm gap-1 text-primary" onClick={() => navigate("/pricing")} data-testid="button-upgrade">
                        Upgrade <ArrowUpRight className="w-3 h-3 lg:w-4 lg:h-4" />
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3">
                  <div className="grid grid-cols-2 gap-3 lg:gap-5">
                    {[
                      { label: "CC Checks", used: usage.checks, limit: tierLimits.dailyChecks, color: "bg-blue-500" },
                      { label: "Shopify Checks", used: usage.shopifyChecks, limit: tierLimits.dailyShopifyChecks, color: "bg-green-500" },
                      { label: "Gateway Finder", used: usage.findsiteSearches, limit: tierLimits.dailyFindsiteSearches, color: "bg-cyan-500" },
                      { label: "Workers", used: tierLimits.parallelWorkers, limit: tierLimits.parallelWorkers, color: "bg-purple-500", isStatic: true },
                    ].map((item) => {
                      const pct = item.limit === -1 ? 0 : item.limit === 0 ? 100 : Math.min(100, (item.used / item.limit) * 100);
                      const isStatic = "isStatic" in item && item.isStatic;
                      return (
                        <div key={item.label} className="p-2.5 lg:p-4 rounded-lg bg-muted/30 border" data-testid={`usage-${item.label.toLowerCase().replace(/ /g, "-")}`}>
                          <div className="flex items-center justify-between mb-1.5 lg:mb-2.5">
                            <span className="text-[11px] lg:text-sm text-muted-foreground">{item.label}</span>
                            <span className="text-[11px] lg:text-sm font-medium">
                              {isStatic ? item.used : `${item.used}/${formatLimit(item.limit)}`}
                            </span>
                          </div>
                          {!isStatic && item.limit !== 0 && (
                            <div className="h-1.5 lg:h-2.5 rounded-full bg-muted overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${item.color}`}
                                style={{ width: item.limit === -1 ? "5%" : `${pct}%` }}
                              />
                            </div>
                          )}
                          {item.limit === 0 && (
                            <div className="text-[10px] lg:text-xs text-muted-foreground/60">Upgrade to unlock</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-sm lg:text-lg flex items-center gap-2">
                  <span className="lg:text-xl">⚡</span>
                  Quick Actions
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-2 lg:pt-3">
                <StaggerContainer className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2 lg:gap-4">
                  {quickTools.map((tool, i) => {
                    const handleClick = (tool as any).onClick
                      ? (tool as any).onClick
                      : () => navigate(tool.path);
                    const isSpinning = (tool as any).spinning;
                    const isLocked = (tool as any).locked;
                    return (
                      <StaggerItem key={tool.label}>
                      <button
                        className={`relative w-full flex flex-col items-center gap-2 lg:gap-3 rounded-lg border p-3 lg:p-5 transition-all duration-300 cursor-pointer hover:scale-[1.04] hover:shadow-md active:scale-95 ${tool.bg}`}
                        onClick={handleClick}
                        data-testid={`quick-${(tool.path || tool.label).replace("/", "").replace(" ", "-").toLowerCase()}`}
                      >
                        {isLocked && (
                          <span className="absolute top-1.5 right-1.5 text-[9px] lg:text-[10px] font-bold text-violet-400 bg-violet-500/20 rounded px-1">PRO</span>
                        )}
                        <tool.icon className={`w-5 h-5 lg:w-7 lg:h-7 ${tool.color} ${isSpinning ? "animate-spin" : "transition-transform duration-300 group-hover:scale-110"}`} />
                        <span className="text-[11px] lg:text-sm font-medium text-center leading-tight">{tool.label}</span>
                      </button>
                      </StaggerItem>
                    );
                  })}
                </StaggerContainer>
              </CardContent>
            </Card>
          </div>
        )}
      </PageTransition>
    </div>
  );
}
