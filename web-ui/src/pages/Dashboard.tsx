import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { DatasetCard } from "@/components/DatasetCard";
import { api } from "@/lib/api";

const DATASET_LABELS: Record<string, string> = {
  era5: "ERA5",
  "era5-land": "ERA5-LAND",
  inmet: "INMET",
};

const DESCRIPTION_KEY: Record<string, string> = {
  era5: "dashboard.descriptions.era5",
  "era5-land": "dashboard.descriptions.era5-land",
  inmet: "dashboard.descriptions.inmet",
};

export function DashboardPage() {
  const { t } = useTranslation();
  const { data: datasets, isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
          {t("dashboard.title")}
        </h1>
        <p className="mt-1 text-ink-500">{t("dashboard.subtitle")}</p>
      </header>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="card h-56 animate-pulse bg-ink-100" />
          <div className="card h-56 animate-pulse bg-ink-100" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {datasets?.map((ds) => {
            const descKey = DESCRIPTION_KEY[ds.name];
            const description =
              descKey !== undefined
                ? t(descKey)
                : (ds.cds_dataset_id || t("dashboard.fallbackDescription"));
            return (
              <DatasetCard
                key={ds.name}
                dataset={ds.name}
                label={DATASET_LABELS[ds.name] ?? ds.name.toUpperCase()}
                description={description}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
