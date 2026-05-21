import type { ComponentType, SVGProps } from "react";
import { useTranslation } from "react-i18next";

import { BrazilFlag, USFlag } from "@/components/flags";
import { type Lang, SUPPORTED_LANGUAGES, setLang } from "@/i18n";
import { cn } from "@/lib/format";

const FLAGS: Record<Lang, ComponentType<SVGProps<SVGSVGElement>>> = {
  pt: BrazilFlag,
  en: USFlag,
};

const LABELS: Record<Lang, { short: string; long: string }> = {
  pt: { short: "PT", long: "Português" },
  en: { short: "EN", long: "English" },
};

/**
 * Top-right language switcher. Renders one button per supported locale,
 * each showing its national flag as a real SVG (so it looks the same on
 * Windows, macOS and Linux — emoji flags fall back to letter codes on
 * Windows). The active language is highlighted; clicking persists to
 * localStorage via the i18next detector so the choice survives reloads.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n, t } = useTranslation();
  const current = (i18n.resolvedLanguage ?? "pt").slice(0, 2) as Lang;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-ink-200 bg-white p-1 shadow-sm",
        className,
      )}
      role="group"
      aria-label={t("language.portuguese") + " / " + t("language.english")}
    >
      {SUPPORTED_LANGUAGES.map((lng) => {
        const isActive = lng === current;
        const label = LABELS[lng];
        const Flag = FLAGS[lng];
        const title = t("language.switchTo", {
          language: lng === "pt" ? t("language.portuguese") : t("language.english"),
        });
        return (
          <button
            key={lng}
            type="button"
            title={title}
            aria-label={title}
            aria-pressed={isActive}
            onClick={() => setLang(lng)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition",
              isActive
                ? "bg-ocean-600 text-white shadow-sm"
                : "text-ink-500 hover:bg-ink-100 hover:text-ink-700",
            )}
          >
            {/* Real SVG flag — same rendering on every OS. Rounded
                corners + a faint ring so it reads as a "flag chip" and
                not as a coloured glyph stuck inside the button. */}
            <Flag
              className={cn(
                "h-4 w-[22px] shrink-0 overflow-hidden rounded-[3px] ring-1 ring-black/10",
                isActive && "ring-white/30",
              )}
            />
            <span className="tracking-wide">{label.short}</span>
          </button>
        );
      })}
    </div>
  );
}
