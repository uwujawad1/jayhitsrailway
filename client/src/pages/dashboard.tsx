import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Users, Crown, Ban, Zap, Bot, UserCheck } from "lucide-react";
import { PageTransition, StaggerContainer, StaggerItem } from "@/components/page-transition";
import type { BotStats, BotStatus } from "@shared/schema";

function StatCard({
  title,
  value,
  icon: Icon,
  description,
  variant = "default",
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  description?: string;
  variant?: "default" | "success" | "warning" | "destructive";
}) {
  const iconColors = {
    default: "text-muted-foreground",
    success: "text-emerald-500 dark:text-emerald-400",
    warning: "text-amber-500 dark:text-amber-400",
    destructive: "text-red-500 dark:text-red-400",
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className={`w-4 h-4 ${iconColors[variant]}`} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold" data-testid={`text-stat-${title.toLowerCase().replace(/\s+/g, '-')}`}>{value}</div>
        {description && (
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery<BotStats>({
    queryKey: ["/api/stats"],
    refetchInterval: 5000,
  });

  const { data: botStatus, isLoading: statusLoading } = useQuery<BotStatus>({
    queryKey: ["/api/bot/status"],
    refetchInterval: 5000,
  });

  if (statsLoading || statusLoading) {
    return (
      <div className="p-6 space-y-6">
        <div>
          <Skeleton className="h-8 w-48 mb-2" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <PageTransition className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold" data-testid="text-page-title">Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">JayHits Bot Overview</p>
      </div>

      <div className="flex items-center gap-2">
        <Badge variant={botStatus?.running ? "default" : "secondary"} data-testid="badge-bot-status">
          <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${botStatus?.running ? "bg-emerald-400" : "bg-muted-foreground"}`} />
          {botStatus?.running ? "Bot Online" : "Bot Offline"}
        </Badge>
        {botStatus?.startedAt && (
          <span className="text-xs text-muted-foreground">
            Since {new Date(botStatus.startedAt).toLocaleString()}
          </span>
        )}
      </div>

      <StaggerContainer className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <StaggerItem>
          <StatCard
            title="Total Users"
            value={stats?.totalUsers ?? 0}
            icon={Users}
            description="All registered bot users"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            title="Premium Users"
            value={stats?.premiumUsers ?? 0}
            icon={Crown}
            variant="warning"
            description="Active premium subscriptions"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            title="Free Users"
            value={stats?.freeUsers ?? 0}
            icon={UserCheck}
            variant="success"
            description="Free tier users"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            title="Banned Users"
            value={stats?.bannedUsers ?? 0}
            icon={Ban}
            variant="destructive"
            description="Users currently banned"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            title="Gateways"
            value={stats?.totalGateways ?? 0}
            icon={Zap}
            description="Available payment gateways"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            title="Bot Status"
            value={botStatus?.running ? "Running" : "Stopped"}
            icon={Bot}
            variant={botStatus?.running ? "success" : "destructive"}
            description={botStatus?.pid ? `PID: ${botStatus.pid}` : "Not started"}
          />
        </StaggerItem>
      </StaggerContainer>
    </PageTransition>
  );
}
