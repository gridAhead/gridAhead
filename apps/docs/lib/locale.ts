import type { BlumeData, Navigation, UIStrings } from "blume";
import type { LocaleSwitchOption } from "blume/core/types.ts";

export type SiteLocale = "en" | "de";

/** Logical path of a custom page that has a file for every configured locale. */
const localizedHref = (
  path: string,
  code: string,
  defaultLocale: string,
): string => {
  if (code === defaultLocale) {
    return path;
  }
  return path === "/" ? `/${code}` : `/${code}${path}`;
};

/**
 * Language switcher for a custom page. Content pages get one automatically;
 * a page under `pages/` is served only at its own route, so it has to name
 * the other locales itself.
 */
export const localeSwitch = (
  data: BlumeData,
  current: SiteLocale,
  path: string,
): LocaleSwitchOption[] => {
  const i18n = data.config.i18n;
  if (!i18n) {
    return [];
  }
  return i18n.locales.map((locale) => ({
    code: locale.code,
    current: locale.code === current,
    dir: locale.dir,
    href: localizedHref(path, locale.code, i18n.defaultLocale),
    label: locale.label,
    untranslated: false,
  }));
};

export const navigationFor = (
  data: BlumeData,
  locale: SiteLocale,
): Navigation => data.navigationByLocale[locale] ?? data.navigation;

export const uiFor = (data: BlumeData, locale: SiteLocale): UIStrings =>
  data.uiByLocale[locale] ?? data.ui;
