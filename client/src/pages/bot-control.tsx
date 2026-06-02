import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Play, Square, RotateCw, Terminal, Clock, Cpu, Trash2 } from "lucide-react";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import type { BotStatus, BotLog } from "@shared/schema";

export default function BotControl() {
  const { toast } = useToast();

  const { data: botStatus, isLoading: statusLoading } = useQuery<BotStatus>({
    queryKey: ["/api/bot/status"],
    refetchInterval: 5000,
  });

  const { data: logs, isLoading: logsLoading } = useQuery<BotLog[]>({
    queryKey: ["/api/bot/logs"],
    refetchInterval: 5000,
  });

  const startBot = useMutation({
    mutationFn: () => apiRequest("POST", "/api/bot/start"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/status"] });
      queryClient.invalidateQueries({ queryKey: ["/api/stats"] });
      toast({ title: "Bot starting...", description: "The bot process is being launched" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to start bot", description: err.message, variant: "destructive" });
    },
  });

  const stopBot = useMutation({
    mutationFn: () => apiRequest("POST", "/api/bot/stop"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/status"] });
      queryClient.invalidateQueries({ queryKey: ["/api/stats"] });
      toast({ title: "Bot stopped", description: "The bot process has been terminated" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to stop bot", description: err.message, variant: "destructive" });
    },
  });

  const restartBot = useMutation({
    mutationFn: () => apiRequest("POST", "/api/bot/restart"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/status"] });
      queryClient.invalidateQueries({ queryKey: ["/api/stats"] });
      toast({ title: "Bot restarting...", description: "The bot is being restarted" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to restart bot", description: err.message, variant: "destructive" });
    },
  });

  const clearLogs = useMutation({
    mutationFn: () => apiRequest("POST", "/api/bot/logs/clear"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/logs"] });
      toast({ title: "Logs cleared" });
    },
  });

  const formatUptime = (seconds: number | null) => {
    if (!seconds) return "N/A";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  if (statusLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  const isRunning = botStatus?.running ?? false;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold" data-testid="text-page-title">Bot Control</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Manage your Telegram bot process
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${isRunning ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground"}`} />
                <div>
                  <p className="text-sm font-medium">Status</p>
                  <p className="text-xl font-bold" data-testid="text-bot-status">{isRunning ? "Running" : "Stopped"}</p>
                </div>
              </div>
              <Badge variant={isRunning ? "default" : "secondary"}>
                {isRunning ? "Online" : "Offline"}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Clock className="w-5 h-5 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">Uptime</p>
                <p className="text-xl font-bold" data-testid="text-bot-uptime">{formatUptime(botStatus?.uptime ?? null)}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Cpu className="w-5 h-5 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">Process ID</p>
                <p className="text-xl font-bold font-mono" data-testid="text-bot-pid">{botStatus?.pid ?? "N/A"}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-4">
          <CardTitle className="text-base">Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 flex-wrap">
            {!isRunning ? (
              <Button
                onClick={() => startBot.mutate()}
                disabled={startBot.isPending}
                data-testid="button-start-bot"
              >
                <Play className="w-4 h-4 mr-2" />
                {startBot.isPending ? "Starting..." : "Start Bot"}
              </Button>
            ) : (
              <>
                <Button
                  variant="destructive"
                  onClick={() => stopBot.mutate()}
                  disabled={stopBot.isPending}
                  data-testid="button-stop-bot"
                >
                  <Square className="w-4 h-4 mr-2" />
                  {stopBot.isPending ? "Stopping..." : "Stop Bot"}
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
              </>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-muted-foreground" />
            <CardTitle className="text-base">Bot Logs</CardTitle>
            {logs && (
              <Badge variant="secondary" className="text-xs">{logs.length} entries</Badge>
            )}
          </div>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => clearLogs.mutate()}
            data-testid="button-clear-logs"
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-80">
            <div className="font-mono text-xs p-4 space-y-0.5">
              {logsLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <Skeleton key={i} className="h-4 w-full" />
                  ))}
                </div>
              ) : !logs || logs.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <Terminal className="w-8 h-8 mb-2 opacity-40" />
                  <p className="text-sm">No logs yet</p>
                  <p className="text-xs mt-1">Start the bot to see output here</p>
                </div>
              ) : (
                logs.map((log, i) => (
                  <div
                    key={i}
                    className={`py-0.5 leading-relaxed ${
                      log.type === "stderr"
                        ? "text-red-500 dark:text-red-400"
                        : log.type === "system"
                        ? "text-blue-500 dark:text-blue-400"
                        : "text-foreground"
                    }`}
                    data-testid={`text-log-${i}`}
                  >
                    <span className="text-muted-foreground mr-2">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    {log.message}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
