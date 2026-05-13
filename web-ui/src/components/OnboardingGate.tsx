import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Onboarding } from "@/pages/Onboarding";

import { api } from "@/lib/api";

/**
 * Gate that forces the onboarding flow when the app is not yet usable.
 *
 * Unusable means either no `data_dir` configured or no CDS credentials
 * detected. Until both are present, the routed page content is replaced
 * with `<Onboarding>`. The sidebar still renders (children mount nothing),
 * so the user can re-enter Settings later by clicking the sidebar — but
 * Dashboard/Download/Query are blocked.
 */
export function OnboardingGate({ children }: { children: ReactNode }) {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentialStatus,
  });

  if (settings.isLoading || credentials.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-ink-400" />
      </div>
    );
  }

  const dataDir = settings.data?.data_dir?.trim() ?? "";
  const hasCreds = credentials.data?.has_credentials === true;

  if (!dataDir) {
    return <Onboarding initialStep="data-dir" />;
  }
  if (!hasCreds) {
    return <Onboarding initialStep="credentials" />;
  }

  return <>{children}</>;
}
