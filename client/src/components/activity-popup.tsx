import { useState, useEffect, useRef } from "react";
import { Zap, LogIn, Crown, UserCheck, X } from "lucide-react";
import { useAuth } from "@/lib/auth";

interface ActivityEvent {
  id: string;
  type: "hit" | "login" | "premium" | "account_hit";
  userName: string;
  message: string;
  detail?: string;
  timestamp: number;
}

const TYPE_CONFIG: Record<string, { icon: typeof Zap; color: string; bg: string }> = {
  hit: { icon: Zap, color: "text-yellow-400", bg: "from-yellow-500/20 to-orange-500/10" },
  login: { icon: LogIn, color: "text-blue-400", bg: "from-blue-500/20 to-cyan-500/10" },
  premium: { icon: Crown, color: "text-purple-400", bg: "from-purple-500/20 to-pink-500/10" },
  account_hit: { icon: UserCheck, color: "text-green-400", bg: "from-green-500/20 to-emerald-500/10" },
};

export default function ActivityPopup() {
  const { isAuthenticated } = useAuth();
  const [visible, setVisible] = useState<ActivityEvent | null>(null);
  const [exiting, setExiting] = useState(false);
  const lastTimestampRef = useRef(Date.now());
  const seenIdsRef = useRef(new Set<string>());
  const queueRef = useRef<ActivityEvent[]>([]);
  const showingRef = useRef(false);

  useEffect(() => {
    if (!isAuthenticated) return;
    const poll = async () => {
      try {
        const res = await fetch(`/api/activity/recent?after=${lastTimestampRef.current}`, {
          credentials: "include",
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.events && data.events.length > 0) {
          const newEvents = data.events.filter(
            (e: ActivityEvent) => !seenIdsRef.current.has(e.id)
          );
          if (newEvents.length > 0) {
            for (const e of newEvents) seenIdsRef.current.add(e.id);
            lastTimestampRef.current = Math.max(...newEvents.map((e: ActivityEvent) => e.timestamp));
            queueRef.current.push(...newEvents);
            showNext();
          }
        }
      } catch {}
    };

    poll();
    const interval = setInterval(poll, 10000);
    return () => clearInterval(interval);
  }, [isAuthenticated]);

  const showNext = () => {
    if (showingRef.current) return;
    const next = queueRef.current.shift();
    if (!next) return;
    showingRef.current = true;
    setExiting(false);
    setVisible(next);

    setTimeout(() => {
      setExiting(true);
      setTimeout(() => {
        setVisible(null);
        showingRef.current = false;
        showNext();
      }, 500);
    }, 4000);
  };

  const dismiss = () => {
    setExiting(true);
    setTimeout(() => {
      setVisible(null);
      showingRef.current = false;
      showNext();
    }, 300);
  };

  if (!visible) return null;

  const config = TYPE_CONFIG[visible.type] || TYPE_CONFIG.hit;
  const Icon = config.icon;
  const timeAgo = getTimeAgo(visible.timestamp);

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 max-w-sm transition-all duration-500 ${
        exiting ? "translate-x-full opacity-0" : "translate-x-0 opacity-100"
      }`}
      data-testid="activity-popup"
    >
      <div className={`relative overflow-hidden rounded-xl border border-white/10 bg-gradient-to-r ${config.bg} backdrop-blur-xl shadow-2xl`}>
        <div className="absolute inset-0 bg-card/80" />
        <div className="relative p-4">
          <button
            onClick={dismiss}
            className="absolute top-2 right-2 text-muted-foreground hover:text-foreground transition-colors"
            data-testid="button-dismiss-activity"
          >
            <X className="w-3.5 h-3.5" />
          </button>
          <div className="flex items-start gap-3 pr-4">
            <div className={`flex-shrink-0 w-9 h-9 rounded-full bg-background/50 flex items-center justify-center ${config.color}`}>
              <Icon className="w-4.5 h-4.5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground truncate" data-testid="text-activity-message">
                {visible.message}
              </p>
              {visible.detail && (
                <p className="text-xs text-muted-foreground mt-0.5 truncate" data-testid="text-activity-detail">
                  {visible.detail}
                </p>
              )}
              <p className="text-[10px] text-muted-foreground/60 mt-1">{timeAgo}</p>
            </div>
          </div>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-primary/30 to-transparent" />
        </div>
      </div>
    </div>
  );
}

function getTimeAgo(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}
