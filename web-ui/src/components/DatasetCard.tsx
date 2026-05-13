import { useQuery } from "@tanstack/react-query";
import { Database, HardDrive, Layers } from "lucide-react";

import { api } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";

interface Props {
  dataset: string;
  label: string;
  description: string;
}

export function DatasetCard({ dataset, label, description }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["stats", dataset],
    queryFn: () => api.stats(dataset),
    refetchInterval: 10_000,
  });

  return (
    <div className="card flex flex-col gap-5 p-6">
      <header className="flex items-start justify-between">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-ocean-600">
            {dataset}
          </div>
          <h3 className="mt-1 text-xl font-semibold text-ink-800">{label}</h3>
          <p className="mt-1 text-sm text-ink-500">{description}</p>
        </div>
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-600">
          <Database className="h-6 w-6" />
        </div>
      </header>
      <dl className="grid grid-cols-3 gap-4 border-t border-ink-100 pt-5">
        <Metric
          icon={Layers}
          label="Partitions"
          value={isLoading ? "—" : formatNumber(data?.partitions.length ?? 0)}
        />
        <Metric
          icon={Database}
          label="Files"
          value={isLoading ? "—" : formatNumber(data?.parquet_files ?? 0)}
        />
        <Metric
          icon={HardDrive}
          label="On disk"
          value={isLoading ? "—" : formatBytes(data?.total_size_bytes ?? 0)}
        />
      </dl>
      {data?.partitions.length ? (
        <p className="text-xs text-ink-400">
          Coverage: {data.partitions[0]} → {data.partitions[data.partitions.length - 1]}
        </p>
      ) : (
        <p className="text-xs italic text-ink-400">No data downloaded yet.</p>
      )}
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database;
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-ink-400">
        <Icon className="h-3 w-3" />
        {label}
      </dt>
      <dd className="mt-1 text-lg font-semibold text-ink-800">{value}</dd>
    </div>
  );
}
