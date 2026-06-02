import { LayoutDashboard, Users, Bot, Zap, Settings, CreditCard, Scan } from "lucide-react";
import { useLocation, Link } from "wouter";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar";

const navItems = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Users", url: "/users", icon: Users },
  { title: "Bot Control", url: "/bot", icon: Bot },
  { title: "Gateways", url: "/gateways", icon: Zap },
  { title: "Web Checker", url: "/checker", icon: CreditCard },
  { title: "SK/CC Scraper", url: "/scraper", icon: Scan },
  { title: "Settings", url: "/settings", icon: Settings },
];

export function AppSidebar() {
  const [location] = useLocation();

  return (
    <Sidebar variant="inset">
      <SidebarHeader>
        <div className="rounded-2xl border border-white/8 bg-[linear-gradient(145deg,rgba(84,214,165,0.16),rgba(84,214,165,0.03))] p-4 shadow-[0_24px_48px_rgba(0,0,0,0.16)]">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-black/15">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-primary/80">Workspace</p>
              <h2 className="text-base font-semibold text-sidebar-foreground">JayHits</h2>
            </div>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const isActive = location === item.url || (item.url !== "/" && location.startsWith(item.url));
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton asChild isActive={isActive}>
                      <Link href={item.url} data-testid={`link-nav-${item.title.toLowerCase().replace(' ', '-')}`}>
                        <item.icon className="w-4 h-4" />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-3 text-xs text-muted-foreground">
          <div className="mb-1 flex items-center gap-2">
            <Settings className="h-3.5 w-3.5" />
            <span className="font-semibold text-foreground/80">System Build</span>
          </div>
          <span>JayHits Control Surface v1.0.0</span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
