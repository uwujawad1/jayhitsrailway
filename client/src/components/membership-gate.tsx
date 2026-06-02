import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ExternalLink, Users, Megaphone, ShieldAlert, RefreshCw, AlertCircle, CheckCircle2 } from "lucide-react";

interface MembershipData {
  member: boolean;
  status: string;
  groupLink?: string;
  channelLink?: string;
}

function getStatusInfo(status: string) {
  switch (status) {
    case "not_in_channel":
      return { title: "Join Our Channel", message: "You need to join our Telegram Channel to use this checker for free.", missingGroup: false, missingChannel: true };
    case "not_in_group":
      return { title: "Join Our Group", message: "You need to join our Telegram Group to use this checker for free.", missingGroup: true, missingChannel: false };
    case "not_in_group_or_channel":
      return { title: "Join Our Channel & Group", message: "You need to join both our Telegram Channel and Group to use this checker for free.", missingGroup: true, missingChannel: true };
    default:
      return { title: "Join Our Channel & Group", message: "You need to join our Telegram Channel and Group to use this checker for free.", missingGroup: true, missingChannel: true };
  }
}

export function MembershipGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null);

  const { data, isLoading } = useQuery<MembershipData>({
    queryKey: ["/api/user/membership"],
    enabled: isAuthenticated,
    staleTime: 60000,
    refetchInterval: 120000,
  });

  if (!isAuthenticated || isLoading || !data || data.member) {
    return <>{children}</>;
  }

  const groupLink = data.groupLink || "";
  const channelLink = data.channelLink || "";
  const currentStatus = refreshStatus || data.status || "";
  const statusInfo = getStatusInfo(currentStatus);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshStatus(null);
    try {
      const res = await fetch("/api/user/membership?refresh=true", { credentials: "include" });
      const freshData = await res.json();
      queryClient.setQueryData(["/api/user/membership"], freshData);
      if (freshData.member) {
        window.location.reload();
      } else {
        setRefreshStatus(freshData.status || "not_in_group_or_channel");
      }
    } catch {
      setRefreshStatus(null);
    }
    setRefreshing(false);
  };

  return (
    <>
      {children}
      <div className="fixed inset-0 z-[100] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" data-testid="membership-overlay">
        <Card className="w-full max-w-md lg:max-w-lg border-yellow-500/40 bg-background shadow-2xl" data-testid="card-membership">
          <CardHeader className="text-center pb-2 lg:pb-4">
            <div className="flex justify-center mb-3 lg:mb-5">
              <div className="p-3 lg:p-5 rounded-full bg-yellow-500/10 border border-yellow-500/30">
                <ShieldAlert className="w-8 h-8 lg:w-12 lg:h-12 text-yellow-400" />
              </div>
            </div>
            <CardTitle className="text-xl lg:text-2xl">{statusInfo.title}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-4 lg:gap-6 lg:px-8">
            <p className="text-sm lg:text-base text-muted-foreground text-center">
              {statusInfo.message}
            </p>

            <div className="w-full flex flex-col gap-2 lg:gap-3">
              {groupLink && (
                <Button
                  className={`w-full font-semibold lg:h-12 lg:text-base ${
                    statusInfo.missingGroup
                      ? "bg-blue-500 hover:bg-blue-600 text-white"
                      : "bg-green-600/20 border border-green-500/40 text-green-400 hover:bg-green-600/30"
                  }`}
                  onClick={() => window.open(groupLink, "_blank")}
                  data-testid="button-join-group"
                >
                  {statusInfo.missingGroup ? (
                    <Users className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                  )}
                  {statusInfo.missingGroup ? "Join Telegram Group" : "Group Joined"}
                  {statusInfo.missingGroup && <ExternalLink className="w-3.5 h-3.5 lg:w-4 lg:h-4 ml-2" />}
                </Button>
              )}
              {channelLink && (
                <Button
                  className={`w-full font-semibold lg:h-12 lg:text-base ${
                    statusInfo.missingChannel
                      ? "bg-purple-500 hover:bg-purple-600 text-white"
                      : "bg-green-600/20 border border-green-500/40 text-green-400 hover:bg-green-600/30"
                  }`}
                  onClick={() => window.open(channelLink, "_blank")}
                  data-testid="button-join-channel"
                >
                  {statusInfo.missingChannel ? (
                    <Megaphone className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 lg:w-5 lg:h-5 mr-2" />
                  )}
                  {statusInfo.missingChannel ? "Join Telegram Channel" : "Channel Joined"}
                  {statusInfo.missingChannel && <ExternalLink className="w-3.5 h-3.5 lg:w-4 lg:h-4 ml-2" />}
                </Button>
              )}
              {!groupLink && !channelLink && (
                <p className="text-xs lg:text-sm text-yellow-400 text-center">
                  Contact the admin to get the group/channel invite links.
                </p>
              )}
            </div>

            {refreshStatus && (
              <div className="w-full flex items-start gap-2 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                <AlertCircle className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
                <p className="text-xs lg:text-sm text-yellow-300">
                  {currentStatus === "not_in_channel"
                    ? "You're in the Group but not the Channel yet. Join the Channel above and try again."
                    : currentStatus === "not_in_group"
                    ? "You're in the Channel but not the Group yet. Join the Group above and try again."
                    : "Still not detected in both. Make sure you joined using the buttons above, wait a moment, then try again."}
                </p>
              </div>
            )}

            <p className="text-xs lg:text-sm text-muted-foreground text-center">
              After joining, click below to continue
            </p>

            <Button
              variant="outline"
              size="sm"
              className="lg:h-10 lg:text-sm lg:px-6"
              onClick={handleRefresh}
              disabled={refreshing}
              data-testid="button-refresh-membership"
            >
              {refreshing ? (
                <><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Checking...</>
              ) : (
                "I've Joined — Refresh"
              )}
            </Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
