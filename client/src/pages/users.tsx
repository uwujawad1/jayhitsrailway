import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Search, Users as UsersIcon, Crown, Ban, UserCheck, Star, Zap, Gift, DollarSign } from "lucide-react";
import { useState, useMemo } from "react";
import type { BotUser } from "@shared/schema";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";

interface TierUser {
  userId: string;
  tier: string;
  assignedBy: string | null;
  assignedAt: string | null;
  isAdmin: boolean;
}

function FilterCard({
  label,
  count,
  icon: Icon,
  iconClass,
  isActive,
  onClick,
  testId,
}: {
  label: string;
  count: number;
  icon: React.ElementType;
  iconClass: string;
  isActive: boolean;
  onClick: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left w-full"
      data-testid={testId}
    >
      <Card className={`hover-elevate ${isActive ? "ring-1 ring-ring" : ""}`}>
        <CardContent className="p-4 flex items-center gap-3">
          <Icon className={`w-5 h-5 ${iconClass}`} />
          <div>
            <p className="text-2xl font-bold">{count}</p>
            <p className="text-xs text-muted-foreground">{label}</p>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

function TierBadge({ tier }: { tier: string }) {
  switch (tier) {
    case "gold":
      return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30"><Crown className="w-3 h-3 mr-1" />Gold</Badge>;
    case "silver":
      return <Badge className="bg-gray-300/20 text-gray-300 border-gray-400/30"><Star className="w-3 h-3 mr-1" />Silver</Badge>;
    default:
      return <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30"><Zap className="w-3 h-3 mr-1" />Free</Badge>;
  }
}

export default function UsersPage() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [creditUserId, setCreditUserId] = useState("");
  const [creditAmount, setCreditAmount] = useState("0.30");
  const [creditNote, setCreditNote] = useState("");
  const { toast } = useToast();

  const { data: users, isLoading } = useQuery<BotUser[]>({
    queryKey: ["/api/users"],
    refetchInterval: 10000,
  });

  const { data: tierData } = useQuery<TierUser[]>({
    queryKey: ["/api/admin/tiers"],
    refetchInterval: 15000,
  });

  const tierMap = useMemo(() => {
    const map: Record<string, string> = {};
    if (tierData) {
      for (const t of tierData) {
        map[t.userId] = t.tier;
      }
    }
    return map;
  }, [tierData]);

  const setTierMutation = useMutation({
    mutationFn: async ({ userId, tier }: { userId: string; tier: string }) => {
      await apiRequest("POST", "/api/admin/tiers", { userId, tier });
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/tiers"] });
      toast({ title: `Tier updated to ${variables.tier}` });
    },
    onError: () => {
      toast({ title: "Failed to update tier", variant: "destructive" });
    },
  });

  interface ReferralRow {
    userId: string;
    balance: number;
    totalEarned: number;
    referredCount: number;
  }

  const { data: referralStats } = useQuery<{ rows: ReferralRow[]; totalUsedBy: number }>({
    queryKey: ["/api/admin/referral/stats"],
    refetchInterval: 30000,
  });

  const creditMutation = useMutation({
    mutationFn: async ({ userId, amount, note }: { userId: string; amount: string; note: string }) => {
      return await apiRequest("POST", "/api/admin/referral/credit", { userId, amount: parseFloat(amount), note });
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/referral/stats"] });
      toast({ title: `Credited $${data.credited} — new balance: $${data.newBalance}` });
      setCreditUserId("");
      setCreditNote("");
    },
    onError: (err: any) => {
      toast({ title: err.message || "Credit failed", variant: "destructive" });
    },
  });

  const filteredUsers = useMemo(() => {
    if (!users) return [];
    return users.filter((user) => {
      const matchesSearch = user.id.includes(search);
      if (filter === "premium") return matchesSearch && user.isPremium;
      if (filter === "banned") return matchesSearch && user.isBanned;
      if (filter === "free") return matchesSearch && !user.isPremium && !user.isBanned;
      return matchesSearch;
    });
  }, [users, search, filter]);

  const counts = useMemo(() => {
    if (!users) return { total: 0, premium: 0, banned: 0, free: 0 };
    return {
      total: users.length,
      premium: users.filter((u) => u.isPremium).length,
      banned: users.filter((u) => u.isBanned).length,
      free: users.filter((u) => !u.isPremium && !u.isBanned).length,
    };
  }, [users]);

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold" data-testid="text-page-title">Users</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Manage your Telegram bot users
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <FilterCard
          label="Total"
          count={counts.total}
          icon={UsersIcon}
          iconClass="text-muted-foreground"
          isActive={filter === "all"}
          onClick={() => setFilter("all")}
          testId="button-filter-all"
        />
        <FilterCard
          label="Premium"
          count={counts.premium}
          icon={Crown}
          iconClass="text-amber-500 dark:text-amber-400"
          isActive={filter === "premium"}
          onClick={() => setFilter("premium")}
          testId="button-filter-premium"
        />
        <FilterCard
          label="Free"
          count={counts.free}
          icon={UserCheck}
          iconClass="text-emerald-500 dark:text-emerald-400"
          isActive={filter === "free"}
          onClick={() => setFilter("free")}
          testId="button-filter-free"
        />
        <FilterCard
          label="Banned"
          count={counts.banned}
          icon={Ban}
          iconClass="text-red-500 dark:text-red-400"
          isActive={filter === "banned"}
          onClick={() => setFilter("banned")}
          testId="button-filter-banned"
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 pb-4">
          <CardTitle className="text-base">User List</CardTitle>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search by User ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 w-56"
                data-testid="input-search-users"
              />
            </div>
            <Select value={filter} onValueChange={setFilter}>
              <SelectTrigger className="w-32" data-testid="select-user-filter">
                <SelectValue placeholder="Filter" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Users</SelectItem>
                <SelectItem value="premium">Premium</SelectItem>
                <SelectItem value="free">Free</SelectItem>
                <SelectItem value="banned">Banned</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {filteredUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
              <UsersIcon className="w-10 h-10 mb-3 opacity-40" />
              <p className="text-sm font-medium">No users found</p>
              <p className="text-xs mt-1">
                {search ? "Try a different search term" : "Users will appear here once the bot is running"}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Joined</TableHead>
                    <TableHead>Premium Expiry</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUsers.map((user) => {
                    const userTier = tierMap[user.id] || "free";
                    return (
                      <TableRow key={user.id} data-testid={`row-user-${user.id}`}>
                        <TableCell className="font-mono text-sm" data-testid={`text-userid-${user.id}`}>{user.id}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {user.isBanned ? (
                              <Badge variant="destructive" data-testid={`badge-status-${user.id}`}>
                                <Ban className="w-3 h-3 mr-1" />
                                Banned
                              </Badge>
                            ) : user.isPremium ? (
                              <Badge className="bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/20" data-testid={`badge-status-${user.id}`}>
                                <Crown className="w-3 h-3 mr-1" />
                                Premium
                              </Badge>
                            ) : (
                              <Badge variant="secondary" data-testid={`badge-status-${user.id}`}>
                                <UserCheck className="w-3 h-3 mr-1" />
                                Free
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Select
                            value={userTier}
                            onValueChange={(val) => setTierMutation.mutate({ userId: user.id, tier: val })}
                          >
                            <SelectTrigger className="w-28 h-8" data-testid={`select-tier-${user.id}`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="free">
                                <div className="flex items-center gap-1.5">
                                  <Zap className="w-3 h-3 text-blue-400" /> Free
                                </div>
                              </SelectItem>
                              <SelectItem value="silver">
                                <div className="flex items-center gap-1.5">
                                  <Star className="w-3 h-3 text-gray-300" /> Silver
                                </div>
                              </SelectItem>
                              <SelectItem value="gold">
                                <div className="flex items-center gap-1.5">
                                  <Crown className="w-3 h-3 text-amber-400" /> Gold
                                </div>
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground" data-testid={`text-joined-${user.id}`}>
                          {user.joinedAt ? new Date(user.joinedAt).toLocaleDateString() : "N/A"}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground" data-testid={`text-expiry-${user.id}`}>
                          {user.premiumExpiry
                            ? new Date(user.premiumExpiry).toLocaleDateString()
                            : "-"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Referral Credit Tool ───────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gift className="w-5 h-5 text-emerald-500" />
            Referral Credit Tool
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Manually credit referral balance to users who missed their bonus. The credit appears on their referral page and can be redeemed for a subscription plan.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Credit form */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end p-4 bg-muted/40 rounded-lg border border-border">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Telegram User ID</label>
              <Input
                data-testid="input-credit-userid"
                placeholder="e.g. 123456789"
                value={creditUserId}
                onChange={(e) => setCreditUserId(e.target.value.trim())}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Amount ($)</label>
              <Input
                data-testid="input-credit-amount"
                type="number"
                step="0.10"
                min="0.01"
                value={creditAmount}
                onChange={(e) => setCreditAmount(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Note (optional)</label>
              <Input
                data-testid="input-credit-note"
                placeholder="e.g. missed referral bonus"
                value={creditNote}
                onChange={(e) => setCreditNote(e.target.value)}
              />
            </div>
            <Button
              data-testid="button-credit-submit"
              onClick={() => {
                if (!creditUserId) return;
                creditMutation.mutate({ userId: creditUserId, amount: creditAmount, note: creditNote });
              }}
              disabled={creditMutation.isPending || !creditUserId}
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
            >
              <DollarSign className="w-4 h-4 mr-1" />
              {creditMutation.isPending ? "Crediting…" : "Credit Balance"}
            </Button>
          </div>

          {/* Referral leaderboard */}
          {referralStats && referralStats.rows.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-2">
                {referralStats.rows.length} users with referral activity · {referralStats.totalUsedBy} successful referrals applied
              </p>
              <div className="rounded-md border overflow-auto max-h-72">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User ID</TableHead>
                      <TableHead className="text-right">Referred</TableHead>
                      <TableHead className="text-right">Total Earned</TableHead>
                      <TableHead className="text-right">Balance</TableHead>
                      <TableHead className="text-right">Quick Credit</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {referralStats.rows.map((row) => (
                      <TableRow key={row.userId} data-testid={`row-referral-${row.userId}`}>
                        <TableCell className="font-mono text-xs">{row.userId}</TableCell>
                        <TableCell className="text-right text-sm">{row.referredCount}</TableCell>
                        <TableCell className="text-right text-sm text-emerald-500">${row.totalEarned.toFixed(2)}</TableCell>
                        <TableCell className="text-right text-sm font-medium">
                          <span className={row.balance > 0 ? "text-amber-400" : "text-muted-foreground"}>
                            ${row.balance.toFixed(2)}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            data-testid={`button-quick-credit-${row.userId}`}
                            size="sm"
                            variant="outline"
                            className="text-xs h-7 px-2"
                            onClick={() => {
                              setCreditUserId(row.userId);
                              setCreditAmount("0.30");
                            }}
                          >
                            +$0.30
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
