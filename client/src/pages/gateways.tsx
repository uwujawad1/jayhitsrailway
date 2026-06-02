import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Zap, Shield, CreditCard, Star, Wrench, Save, Layers } from "lucide-react";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useToast } from "@/hooks/use-toast";
import { useState, useEffect } from "react";
import type { Gateway } from "@shared/schema";

interface Tool {
  id: string;
  name: string;
  category: string;
  enabled: boolean;
  premiumOnly: boolean;
}

interface BotSettings {
  mass_check_enabled: boolean;
  inline_mass_limit: number;
  file_mass_limit: number;
}

const categoryConfig: Record<string, { label: string; icon: React.ElementType }> = {
  auth: { label: "Auth Gateways", icon: Shield },
  charge: { label: "Charge Gateways", icon: CreditCard },
  mass: { label: "Mass Gateways", icon: Layers },
  special: { label: "Special Gateways", icon: Star },
  tools: { label: "Tools", icon: Wrench },
};

export default function GatewaysPage() {
  const { toast } = useToast();

  const { data: gateways, isLoading: gwLoading } = useQuery<Gateway[]>({
    queryKey: ["/api/gateways"],
  });

  const { data: tools, isLoading: toolsLoading } = useQuery<Tool[]>({
    queryKey: ["/api/tools"],
  });

  const { data: settings, isLoading: settingsLoading } = useQuery<BotSettings>({
    queryKey: ["/api/bot/settings"],
  });

  const [massEnabled, setMassEnabled] = useState(true);
  const [inlineLimit, setInlineLimit] = useState(10);
  const [fileLimit, setFileLimit] = useState(300);
  const [hasSettingsEdits, setHasSettingsEdits] = useState(false);

  useEffect(() => {
    if (settings) {
      setMassEnabled(settings.mass_check_enabled);
      setInlineLimit(settings.inline_mass_limit);
      setFileLimit(settings.file_mass_limit);
      setHasSettingsEdits(false);
    }
  }, [settings]);

  const toggleGateway = useMutation({
    mutationFn: async ({ id, field, value }: { id: string; field: "enabled" | "premium_only"; value: boolean }) => {
      return apiRequest("PATCH", `/api/gateways/${id}`, { [field]: value });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/gateways"] });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to update", description: err.message, variant: "destructive" });
    },
  });

  const toggleTool = useMutation({
    mutationFn: async ({ id, field, value }: { id: string; field: "enabled" | "premium_only"; value: boolean }) => {
      return apiRequest("PATCH", `/api/tools/${id}`, { [field]: value });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to update", description: err.message, variant: "destructive" });
    },
  });

  const saveSettings = useMutation({
    mutationFn: async () => {
      return apiRequest("PUT", "/api/bot/settings", {
        mass_check_enabled: massEnabled,
        inline_mass_limit: inlineLimit,
        file_mass_limit: fileLimit,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/bot/settings"] });
      setHasSettingsEdits(false);
      toast({ title: "Settings saved" });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to save", description: err.message, variant: "destructive" });
    },
  });

  const isLoading = gwLoading || toolsLoading || settingsLoading;

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-32" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 9 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    );
  }

  const grouped: Record<string, Gateway[]> = {};
  gateways?.forEach((gw) => {
    const cat = gw.category || "other";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(gw);
  });

  const categoryOrder = ["auth", "charge", "mass", "special"];
  const allCategories = Object.keys(grouped);
  const orderedCategories = [...categoryOrder.filter(c => grouped[c]), ...allCategories.filter(c => !categoryOrder.includes(c))];

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold" data-testid="text-page-title">Gateway & Tool Management</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Control gateway access, tool permissions, and mass check settings
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="secondary" data-testid="badge-total-gateways">
          {gateways?.length ?? 0} gateways
        </Badge>
        <Badge variant="secondary" data-testid="badge-total-tools">
          {tools?.length ?? 0} tools
        </Badge>
        <Badge variant={massEnabled ? "default" : "destructive"} data-testid="badge-mass-status">
          Mass Check: {massEnabled ? "ON" : "OFF"}
        </Badge>
      </div>

      <Card data-testid="card-mass-settings">
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-4">
          <Layers className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Mass Check Settings</CardTitle>
          {hasSettingsEdits && (
            <Badge variant="secondary" className="ml-auto text-xs">Unsaved</Badge>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Mass Checking</p>
              <p className="text-xs text-muted-foreground">Enable or disable all mass checking</p>
            </div>
            <Switch
              checked={massEnabled}
              onCheckedChange={(v) => { setMassEnabled(v); setHasSettingsEdits(true); }}
              data-testid="switch-mass-enabled"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">Inline Mass Limit</label>
              <p className="text-xs text-muted-foreground">Max cards per message</p>
              <Input
                type="number"
                min={1}
                max={100}
                value={inlineLimit}
                onChange={(e) => { const v = parseInt(e.target.value); if (!isNaN(v) && v > 0) { setInlineLimit(v); setHasSettingsEdits(true); } }}
                data-testid="input-inline-limit"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">File Mass Limit</label>
              <p className="text-xs text-muted-foreground">Max cards per file upload</p>
              <Input
                type="number"
                min={1}
                max={10000}
                value={fileLimit}
                onChange={(e) => { const v = parseInt(e.target.value); if (!isNaN(v) && v > 0) { setFileLimit(v); setHasSettingsEdits(true); } }}
                data-testid="input-file-limit"
              />
            </div>
          </div>
          {hasSettingsEdits && (
            <Button
              onClick={() => saveSettings.mutate()}
              disabled={saveSettings.isPending}
              size="sm"
              data-testid="button-save-mass-settings"
            >
              <Save className="w-4 h-4 mr-2" />
              {saveSettings.isPending ? "Saving..." : "Save Settings"}
            </Button>
          )}
        </CardContent>
      </Card>

      {!gateways || gateways.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Zap className="w-10 h-10 mb-3 opacity-40" />
            <p className="text-sm font-medium">No gateways configured</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-8">
          {orderedCategories.map((cat) => {
            const gates = grouped[cat];
            if (!gates || gates.length === 0) return null;
            const config = categoryConfig[cat] || { label: cat, icon: Zap };
            const Icon = config.icon;

            return (
              <div key={cat} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon className="w-5 h-5 text-muted-foreground" />
                  <h2 className="text-lg font-semibold" data-testid={`text-category-${cat}`}>
                    {config.label}
                  </h2>
                  <Badge variant="secondary" className="text-xs" data-testid={`badge-category-count-${cat}`}>{gates.length}</Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {gates.map((gw) => (
                    <Card key={gw.id} className={`transition-opacity ${!gw.enabled ? "opacity-50" : ""}`} data-testid={`card-gateway-${gw.id}`}>
                      <CardContent className="p-4 space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-semibold" data-testid={`text-gateway-name-${gw.id}`}>{gw.name}</p>
                            <p className="text-xs text-muted-foreground font-mono mt-0.5" data-testid={`text-gateway-alias-${gw.id}`}>/{gw.id}</p>
                          </div>
                          <Badge variant="secondary" className="text-xs" data-testid={`badge-gateway-type-${gw.id}`}>
                            {gw.type}
                          </Badge>
                        </div>
                        <div className="flex items-center justify-between gap-4 pt-1 border-t">
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={gw.enabled}
                              onCheckedChange={(v) => toggleGateway.mutate({ id: gw.id, field: "enabled", value: v })}
                              data-testid={`switch-gateway-enabled-${gw.id}`}
                            />
                            <span className="text-xs text-muted-foreground">{gw.enabled ? "On" : "Off"}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">Premium</span>
                            <Switch
                              checked={gw.premiumOnly}
                              onCheckedChange={(v) => toggleGateway.mutate({ id: gw.id, field: "premium_only", value: v })}
                              data-testid={`switch-gateway-premium-${gw.id}`}
                            />
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tools && tools.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Wrench className="w-5 h-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold" data-testid="text-category-tools">
              Tools
            </h2>
            <Badge variant="secondary" className="text-xs" data-testid="badge-category-count-tools">{tools.length}</Badge>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {tools.map((tool) => (
              <Card key={tool.id} className={`transition-opacity ${!tool.enabled ? "opacity-50" : ""}`} data-testid={`card-tool-${tool.id}`}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold" data-testid={`text-tool-name-${tool.id}`}>{tool.name}</p>
                      <p className="text-xs text-muted-foreground font-mono mt-0.5" data-testid={`text-tool-alias-${tool.id}`}>/{tool.id}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-4 pt-1 border-t">
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={tool.enabled}
                        onCheckedChange={(v) => toggleTool.mutate({ id: tool.id, field: "enabled", value: v })}
                        data-testid={`switch-tool-enabled-${tool.id}`}
                      />
                      <span className="text-xs text-muted-foreground">{tool.enabled ? "On" : "Off"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">Premium</span>
                      <Switch
                        checked={tool.premiumOnly}
                        onCheckedChange={(v) => toggleTool.mutate({ id: tool.id, field: "premium_only", value: v })}
                        data-testid={`switch-tool-premium-${tool.id}`}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
