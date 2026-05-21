// i18n initialisation. Portuguese is the project's primary language so
// it is the default + fallback. The user can flip to English via the
// LanguageSwitcher in the top-right of every page; the choice persists
// in localStorage so reloads keep it.

import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import { en } from "./locales/en";
import { pt } from "./locales/pt";

export const SUPPORTED_LANGUAGES = ["pt", "en"] as const;
export type Lang = (typeof SUPPORTED_LANGUAGES)[number];

const STORAGE_KEY = "era5_lang";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      pt: { translation: pt },
      en: { translation: en },
    },
    fallbackLng: "pt",
    supportedLngs: SUPPORTED_LANGUAGES as unknown as string[],
    interpolation: {
      // React already escapes by default.
      escapeValue: false,
    },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: STORAGE_KEY,
      caches: ["localStorage"],
    },
  });

export function getCurrentLang(): Lang {
  const raw = i18n.language?.slice(0, 2);
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(raw) ? (raw as Lang) : "pt";
}

export function setLang(lang: Lang): void {
  void i18n.changeLanguage(lang);
}

export default i18n;
