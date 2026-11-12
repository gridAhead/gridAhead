import { defineConfig } from "blume";

export default defineConfig({
  title: "gridAhead",
  description:
    "Geocode and georeference distribution grid expansion plans so the public can use them.",
  logo: {
    image: "/logos/gridahead.svg",
    text: "",
  },
  navigation: {
    tabs: [
      {
        label: { de: "Doku", en: "Docs" },
        path: "/docs",
      },
      {
        label: "Blog",
        path: "/blog",
      },
    ],
  },
  content: {
    root: "content",
  },
  i18n: {
    defaultLocale: "en",
    locales: [
      { code: "en", label: "English" },
      { code: "de", label: "Deutsch" },
    ],
  },
  lastModified: "git",
  github: {
    owner: "gridAhead",
    repo: "gridAhead",
  },
});
