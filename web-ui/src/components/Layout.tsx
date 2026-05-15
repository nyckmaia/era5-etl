import { Link } from "@tanstack/react-router";
import {
  CloudDownload,
  BarChart3,
  Database,
  Settings as SettingsIcon,
  Globe2,
  MapPin,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import type { ReactNode } from "react";

import { OnboardingGate } from "@/components/OnboardingGate";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { cn } from "@/lib/format";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { to: "/inventory", label: "Inventory", icon: MapPin },
  { to: "/download", label: "Download", icon: CloudDownload },
  { to: "/query", label: "Query", icon: Database },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useLocalStorage(
    "layout.sidebarCollapsed",
    false,
  );

  return (
    <div className="flex h-full">
      <aside
        className={cn(
          "flex flex-col border-r border-ink-100 bg-white transition-[width] duration-200",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div
          className={cn(
            "flex items-center py-5",
            collapsed ? "justify-center px-2" : "gap-2 px-6",
          )}
        >
          <div className="rounded-lg bg-ocean-600 p-2 text-white">
            <Globe2 className="h-5 w-5" />
          </div>
          {!collapsed ? (
            <div>
              <div className="text-sm font-semibold text-ink-800">ERA5-ETL</div>
              <div className="text-[10px] uppercase tracking-wide text-ink-400">
                Climate data
              </div>
            </div>
          ) : null}
        </div>

        <nav className="flex-1 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={cn(
                "group flex items-center rounded-xl px-3 py-2 text-sm font-medium text-ink-500 transition hover:bg-ink-100 hover:text-ink-800",
                collapsed ? "justify-center" : "gap-3",
              )}
              activeProps={{
                className: cn(
                  "group flex items-center rounded-xl px-3 py-2 text-sm font-medium",
                  collapsed ? "justify-center" : "gap-3",
                  "bg-ocean-600/10 text-ocean-700",
                ),
              }}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed ? label : null}
            </Link>
          ))}
        </nav>

        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Expandir menu" : "Recolher menu"}
          aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          className={cn(
            "mx-3 mb-2 flex items-center rounded-xl px-3 py-2 text-sm font-medium text-ink-400 transition hover:bg-ink-100 hover:text-ink-700",
            collapsed ? "justify-center" : "gap-3",
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4 shrink-0" />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4 shrink-0" />
              Recolher
            </>
          )}
        </button>

        {!collapsed ? (
          <footer className="px-6 py-4 text-[11px] text-ink-400">
            ERA5 / ERA5-LAND · Copernicus CDS
          </footer>
        ) : null}
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <OnboardingGate>{children}</OnboardingGate>
        </div>
      </main>
    </div>
  );
}
