import { useQuery } from "@tanstack/react-query";

import { DatasetCard } from "@/components/DatasetCard";
import { api } from "@/lib/api";

const DATASET_LABELS: Record<string, { label: string; description: string }> = {
  era5: {
    label: "ERA5",
    description:
      "Atmospheric reanalysis on a 0.25° single-level grid. Temperature, wind, pressure, radiation, clouds.",
  },
  "era5-land": {
    label: "ERA5-LAND",
    description:
      "Land-surface reanalysis on a 0.1° grid. Surface temperature, soil moisture, snow, precipitation.",
  },
  inmet: {
    label: "INMET",
    description:
      "Estações meteorológicas do INMET (Brasil). Uma série por estação/ano; comparável ao ERA5/ERA5-LAND via era5_inmet.",
  },
};

export function DashboardPage() {
  const { data: datasets, isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">Dashboard</h1>
        <p className="mt-1 text-ink-500">
          Two independent climate datasets, each managed with its own variables and parquet
          partitions. Both download in NetCDF4 and convert to Parquet.
        </p>
      </header>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="card h-56 animate-pulse bg-ink-100" />
          <div className="card h-56 animate-pulse bg-ink-100" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {datasets?.map((ds) => (
            <DatasetCard
              key={ds.name}
              dataset={ds.name}
              label={DATASET_LABELS[ds.name]?.label ?? ds.name.toUpperCase()}
              description={
                DATASET_LABELS[ds.name]?.description ||
                ds.cds_dataset_id ||
                "Fonte de dados."
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
