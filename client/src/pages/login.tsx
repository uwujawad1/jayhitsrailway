import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { CreditCard, Send, ShieldCheck, Loader2, KeyRound, ExternalLink, MessageCircle, Clock, Gift, Ban } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/lib/auth";
import { apiRequest } from "@/lib/queryClient";
import { useQueryClient } from "@tanstack/react-query";

const OTP_COOLDOWN = 30; // seconds before another OTP can be requested

export default function LoginPage() {
  const [step, setStep] = useState<"id" | "otp">("id");
  const [userId, setUserId] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [botUsername, setBotUsername] = useState("JayHitsBot");
  const [cooldown, setCooldown] = useState(0); // seconds remaining before next OTP allowed
  const [banned, setBanned] = useState(false);
  const { toast } = useToast();
  const { refetchSession, isBanned } = useAuth();
  const queryClient = useQueryClient();
  const requestingRef = useRef(false);
  const cooldownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Capture referral code from URL ?ref=REFxxxxxxx and persist in localStorage
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ref = params.get("ref");
    if (ref && /^REF\d{5,15}$/i.test(ref)) {
      localStorage.setItem("pendingReferral", ref.toUpperCase());
    }
  }, []);

  useEffect(() => {
    fetch("/api/bot/username")
      .then(r => r.json())
      .then(d => { if (d.username) setBotUsername(d.username); })
      .catch(() => {});
  }, []);

  // Clear interval on unmount
  useEffect(() => {
    return () => {
      if (cooldownRef.current) clearInterval(cooldownRef.current);
    };
  }, []);

  const startCooldown = (seconds = OTP_COOLDOWN) => {
    setCooldown(seconds);
    if (cooldownRef.current) clearInterval(cooldownRef.current);
    cooldownRef.current = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) {
          clearInterval(cooldownRef.current!);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const requestOtp = async () => {
    if (requestingRef.current || cooldown > 0) return;
    if (!userId.trim() || !/^\d{5,15}$/.test(userId.trim())) {
      toast({ title: "Enter a valid Telegram user ID", variant: "destructive" });
      return;
    }

    requestingRef.current = true;
    setLoading(true);
    try {
      const res = await apiRequest("POST", "/api/auth/request-otp", { userId: userId.trim() });
      const data = await res.json();
      if (res.status === 403) {
        setBanned(true);
        return;
      }
      if (res.ok && data.success) {
        setStep("otp");
        startCooldown(OTP_COOLDOWN);
        toast({ title: "OTP sent to your Telegram" });
      } else {
        // If server says wait X seconds, parse that and start cooldown
        const waitMatch = (data.message || "").match(/wait (\d+)s/);
        if (waitMatch) startCooldown(parseInt(waitMatch[1]));
        toast({ title: data.message || "Failed to send OTP", variant: "destructive" });
      }
    } catch (err: any) {
      const msg = err?.message || "Failed to send OTP";
      toast({ title: msg, variant: "destructive" });
    } finally {
      setLoading(false);
      requestingRef.current = false;
    }
  };

  const verifyOtp = async () => {
    if (requestingRef.current) return;
    if (!otp.trim() || otp.trim().length !== 6) {
      toast({ title: "Enter the 6-digit OTP", variant: "destructive" });
      return;
    }

    requestingRef.current = true;
    setLoading(true);
    try {
      const res = await apiRequest("POST", "/api/auth/verify-otp", {
        userId: userId.trim(),
        otp: otp.trim(),
      });
      const data = await res.json();
      if (res.status === 403) {
        setBanned(true);
        return;
      }
      if (data.success) {
        // Apply pending referral code (if user came via a referral link)
        const pendingRef = localStorage.getItem("pendingReferral");
        if (pendingRef) {
          localStorage.removeItem("pendingReferral");
          apiRequest("POST", "/api/referral/apply", { code: pendingRef }).catch(() => {});
        }
        toast({ title: "Login successful" });
        // Directly update the session cache from the verify-otp response data —
        // avoids a second network round-trip that can race with the session write.
        if (data.user) {
          queryClient.setQueryData(["/api/auth/session"], {
            authenticated: true,
            user: data.user,
          });
        } else {
          await refetchSession();
        }
      } else {
        toast({ title: data.message || "Verification failed", variant: "destructive" });
      }
    } catch (err: any) {
      const msg = err?.message || "Verification failed";
      toast({ title: msg, variant: "destructive" });
    } finally {
      setLoading(false);
      requestingRef.current = false;
    }
  };

  const handleUseDifferentId = () => {
    setStep("id");
    setOtp("");
    // Don't reset cooldown — user already requested an OTP for this session
  };

  if (banned || isBanned) {
    return (
      <div className="app-shell relative flex min-h-screen flex-col items-center justify-center p-4">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(196,93,58,0.14),transparent_35%),radial-gradient(circle_at_bottom,rgba(84,214,165,0.12),transparent_30%)]" />
        <div className="flex flex-col items-center gap-6 w-full max-w-sm">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl border border-destructive/25 bg-destructive/10 shadow-[0_20px_50px_rgba(165,54,45,0.16)]">
            <Ban className="w-8 h-8 text-destructive" />
          </div>
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold text-destructive" data-testid="text-banned-title">You Have Been Banned</h1>
            <p className="text-sm text-muted-foreground">You are no longer able to use JayHits.</p>
          </div>
          <Card className="w-full border-destructive/30" data-testid="card-banned">
            <CardContent className="pt-6 space-y-4 text-center">
              <p className="text-sm text-muted-foreground">If you believe this was a mistake, contact the admin to appeal your ban.</p>
              <a
                href={`https://t.me/${import.meta.env.VITE_ADMIN_TELEGRAM_USERNAME || "JayHitsAdmin"}`}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="link-appeal"
              >
                <Button variant="outline" className="w-full gap-2">
                  <MessageCircle className="w-4 h-4" />
                  Contact Admin to Appeal
                  <ExternalLink className="w-3 h-3 opacity-60" />
                </Button>
              </a>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell relative flex min-h-screen flex-col items-center justify-center p-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(84,214,165,0.16),transparent_30%),radial-gradient(circle_at_bottom_right,rgba(196,93,58,0.12),transparent_34%)]" />
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="relative z-10 flex w-full max-w-sm flex-col items-center gap-7 md:max-w-md lg:max-w-lg"
      >
        <div className="flex flex-col items-center gap-3 lg:gap-4">
          <div className="app-chip">Secure Workspace Access</div>
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.1, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="flex h-16 w-16 items-center justify-center rounded-2xl border border-white/12 bg-[linear-gradient(145deg,rgba(84,214,165,0.22),rgba(84,214,165,0.06))] shadow-[0_28px_60px_rgba(84,214,165,0.16)] transition-transform duration-300 hover:scale-105 lg:h-20 lg:w-20"
            data-testid="logo-icon"
          >
            <CreditCard className="w-7 h-7 lg:w-9 lg:h-9 text-primary-foreground" />
          </motion.div>
          <div className="space-y-2 text-center">
            <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl" data-testid="text-app-title">JayHits</h1>
            <p className="mx-auto max-w-sm text-sm leading-6 text-muted-foreground lg:text-base">Enter with your Telegram identity and keep the full workspace behind one clean verification flow.</p>
          </div>
        </div>

        <Card className="w-full animate-fade-in-up overflow-hidden" style={{ animationDelay: "150ms" }}>
          <CardHeader className="border-b border-white/6 pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              {step === "id" ? (
                <>
                  <Send className="w-4 h-4" />
                  Enter Your Telegram ID
                </>
              ) : (
                <>
                  <KeyRound className="w-4 h-4" />
                  Enter OTP
                </>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {step === "id" ? (
              <>
                <div className="flex flex-col gap-3">
                  <Input
                    placeholder="Your Telegram User ID"
                    value={userId}
                    onChange={e => setUserId(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={e => { if (e.key === "Enter" && userId.trim() && !loading && cooldown === 0) requestOtp(); }}
                    disabled={loading}
                    maxLength={15}
                    data-testid="input-user-id"
                  />

                  <div className="rounded-lg border border-white/8 bg-white/[0.03] p-4">
                    <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-primary/90">
                      <MessageCircle className="w-3.5 h-3.5" />
                      How to get your User ID
                    </p>
                    <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">1</span>
                        <span>Open & start our Telegram bot</span>
                      </div>
                      <div className="flex items-center justify-center my-1">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs"
                          onClick={() => window.open(`https://t.me/${botUsername}`, "_blank")}
                          data-testid="button-open-bot"
                        >
                          @{botUsername}
                          <ExternalLink className="w-3 h-3 ml-1.5" />
                        </Button>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">2</span>
                        <span>Click <strong>/start</strong> to get your User ID</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">3</span>
                        <span>Copy & paste your ID above</span>
                      </div>
                    </div>
                  </div>
                </div>
                <Button
                  type="button"
                  onClick={requestOtp}
                  disabled={loading || !userId.trim() || cooldown > 0}
                  className="w-full"
                  data-testid="button-request-otp"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : cooldown > 0 ? (
                    <Clock className="w-4 h-4 mr-2" />
                  ) : (
                    <Send className="w-4 h-4 mr-2" />
                  )}
                  {cooldown > 0 ? `Resend in ${cooldown}s` : "Send OTP"}
                </Button>
              </>
            ) : (
              <>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <ShieldCheck className="w-3.5 h-3.5 text-primary" />
                    OTP sent to Telegram ID: <Badge variant="secondary" className="text-xs">{userId}</Badge>
                  </div>
                  <Input
                    placeholder="Enter 6-digit OTP"
                    value={otp}
                    onChange={e => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    onKeyDown={e => { if (e.key === "Enter" && otp.length === 6 && !loading) verifyOtp(); }}
                    disabled={loading}
                    maxLength={6}
                    className="text-center text-lg tracking-widest font-mono"
                    data-testid="input-otp"
                    autoFocus
                  />
                </div>
                <Button
                  type="button"
                  onClick={verifyOtp}
                  disabled={loading || otp.length !== 6}
                  className="w-full"
                  data-testid="button-verify-otp"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <ShieldCheck className="w-4 h-4 mr-2" />
                  )}
                  Verify & Login
                </Button>

                {/* Resend OTP */}
                {cooldown > 0 ? (
                  <p className="text-xs text-muted-foreground text-center flex items-center justify-center gap-1.5">
                    <Clock className="w-3.5 h-3.5" />
                    Resend available in {cooldown}s
                  </p>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={requestOtp}
                    disabled={loading}
                    data-testid="button-resend-otp"
                  >
                    Resend OTP
                  </Button>
                )}

                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleUseDifferentId}
                  disabled={loading}
                  data-testid="button-back-to-id"
                >
                  Use different ID
                </Button>
              </>
            )}
          </CardContent>
        </Card>

        <p className="text-xs text-muted-foreground text-center">
          Don't have access? Contact admin on Telegram
        </p>
      </motion.div>
    </div>
  );
}
