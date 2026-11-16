import { defineConfig } from "blume";

export default defineConfig({
  title: "gridAhead",
  description:
    "An open-source and open-data project that turns published German grid expansion plans into accessible, georeferenced datasets.",
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
