import { Switch, Route } from "wouter";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AdminSidebar } from "@/components/admin-sidebar";
import { Bot } from "lucide-react";
import Dashboard from "@/pages/dashboard";
import UsersPage from "@/pages/users";
import BotControl from "@/pages/bot-control";
import GatewaysPage from "@/pages/gateways";
import SettingsPage from "@/pages/settings";
import FakeLogsPage from "@/pages/fake-logs";
import NotFound from "@/pages/not-found";

export default function AdminLayout() {
  const style = {
    "--sidebar-width": "16rem",
    "--sidebar-width-icon": "3rem",
  };

  return (
    <SidebarProvider style={style as React.CSSProperties}>
      <div className="app-shell flex h-screen w-full">
        <AdminSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="app-topbar">
            <div className="flex items-center gap-3">
              <SidebarTrigger data-testid="button-sidebar-toggle" />
              <div className="app-topbar__title">
                <div className="app-topbar__icon">
                  <Bot className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary/80">Operator Console</p>
                  <h1 className="text-base font-semibold text-foreground lg:text-lg">Administration</h1>
                </div>
              </div>
            </div>
            <div className="app-chip">JayHits Admin</div>
          </header>
          <main className="flex-1 overflow-auto">
            <Switch>
              <Route path="/admin" component={Dashboard} />
              <Route path="/admin/users" component={UsersPage} />
              <Route path="/admin/bot" component={BotControl} />
              <Route path="/admin/gateways" component={GatewaysPage} />
              <Route path="/admin/settings" component={SettingsPage} />
              <Route path="/admin/fake-logs" component={FakeLogsPage} />
              <Route component={NotFound} />
            </Switch>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}
