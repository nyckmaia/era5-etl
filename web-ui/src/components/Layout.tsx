import { Link } from "@tanstack/react-router";
import {
  CloudDownload,
  BarChart3,
  Database,
  Settings as SettingsIcon,
  Globe2,
  MapPin,
} from "lucide-react";
import type { ReactNode } from "react";

import { OnboardingGate } from "@/components/OnboardingGate";
import { cn } from "@/lib/format";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { to: "/inventory", label: "Inventory", icon: MapPin },
  { to: "/download", label: "Download", icon: CloudDownload },
  { to: "/query", label: "Query", icon: Database },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full">
      <aside className="flex w-60 flex-col border-r border-ink-100 bg-white">
        <div className="flex items-center gap-2 px-6 py-5">
          <div className="rounded-lg bg-ocean-600 p-2 text-white">
            <Globe2 className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-ink-800">ERA5-ETL</div>
            <div className="text-[10px] uppercase tracking-wide text-ink-400">
              Climate data
            </div>
          </div>
        </div>
        <nav className="flex-1 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-ink-500 transition hover:bg-ink-100 hover:text-ink-800"
              activeProps={{
                className: cn(
                  "group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium",
                  "bg-ocean-600/10 text-ocean-700",
                ),
              }}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <footer className="px-6 py-4 text-[11px] text-ink-400">
          ERA5 / ERA5-LAND · Copernicus CDS
        </footer>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <OnboardingGate>{children}</OnboardingGate>
        </div>
      </main>
    </div>
  );
}
