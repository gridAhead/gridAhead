import type { SiteLocale } from "../../lib/locale.ts";

export interface LandingLink {
  href: string;
  label: string;
}

export interface LandingActivity {
  body: string;
  link?: LandingLink;
  title: string;
}

export interface LandingCopy {
  activities: LandingActivity[];
  announcement: LandingLink;
  cooperation: string;
  cooperationKicker: string;
  description: string;
  docs: LandingLink;
  facts: { body: string; title: string }[];
  figure: string;
  fundedAfter: string;
  fundedBefore: string;
  fundedKicker: string;
  headline: [string, string, string];
  infrastructure: string;
  introduction: LandingLink;
  kicker: string;
  lead: string;
  problem: [string, string];
  problemLead: string;
  title: string;
  work: [string, string];
}

const github = "https://github.com/gridahead/gridahead";

export const landingCopy: Record<SiteLocale, LandingCopy> = {
  en: {
    activities: [
      {
        body: "Locate announced measures from the 2024 and 2026 plans, so it is clear where and when the grid near a site will be reinforced.",
        title: "Geocode planned measures",
      },
      {
        body: "Digitize the maps in the plans and enrich them with other public data. Studies can then use real medium-voltage topologies instead of synthetic model grids.",
        title: "Georeference grid maps",
      },
      {
        body: "Publish results under open licences whenever possible, so others can reuse one versioned dataset instead of starting from the original documents again.",
        title: "Make it accessible",
      },
      {
        body: "An open community that uses, reviews, and develops the data and the methods.",
        link: { href: github, label: "Help on GitHub." },
        title: "Build a community",
      },
    ],
    announcement: {
      href: "/blog/2026-11-17-introducing-gridahead",
      label: "Our announcement",
    },
    cooperation: "A cooperation of the Reiner Lemoine Institute and Goal100.",
    cooperationKicker: "Cooperation",
    description:
      "An open-source and open-data project that turns published German grid expansion plans into accessible, georeferenced datasets.",
    docs: { href: "/docs", label: "Read the docs" },
    facts: [
      {
        body: "80 of 85 operators have published measures. About 20,000 of the more than 33,000 are ongoing or planned. Where they are is still generally unclear.",
        title: "Second round, 2026",
      },
      {
        body: "Most operators now use a common spreadsheet format. The 2024 round was PDF only. Measures still have no coordinates, and the grid maps are still images in the reports.",
        title: "Spreadsheets, not maps",
      },
      {
        body: "Operators with 100,000 or more customers, and smaller ones with significant wind or solar curtailment, must publish a plan on VNBdigital under §§ 14d and 14e EnWG.",
        title: "Every two years",
      },
    ],
    figure:
      "Stylized map of Germany: hexagons shaded by the density of grid expansion measures, overlaid with a schematic grid of existing and planned lines and substations.",
    fundedAfter: ".",
    fundedBefore:
      "Goal100's initiative for gridAhead is jointly funded by Google.org and the Veolia Stiftung, and hosted by ",
    fundedKicker: "Funded by",
    headline: ["Turning grid plans", "into data.", "Open and georeferenced."],
    infrastructure:
      "Making these plans easier to use does not conflict with the protection of critical infrastructure. gridAhead works only with information distribution system operators have already published.",
    introduction: { href: "/docs", label: "Read the introduction" },
    kicker: "Reiner Lemoine Institute & Goal100",
    lead: "Since the end of October, Germany's larger distribution system operators have published a second round of grid expansion plans, more than 33,000 measures. The data is still hard to use. gridAhead turns those published plans into open, georeferenced datasets.",
    problem: ["Over 33,000 measures.", "Still hard to use as data."],
    problemLead:
      "New wind and solar plants, storage, heat pumps, and charging points can connect only as fast as the distribution grid is reinforced. The plans for that work are public. Places, coordinates, and open licences are mostly still missing.",
    title: "gridAhead — Turning grid plans into data",
    work: ["From published plans to open data.", "What gridAhead is building."],
  },
  de: {
    activities: [
      {
        body: "Angekündigte Maßnahmen aus den Plänen 2024 und 2026 verorten, damit klar ist, wo und wann das Netz in der Nähe eines Standorts verstärkt wird.",
        title: "Geplante Maßnahmen geokodieren",
      },
      {
        body: "Die Karten aus den Plänen digitalisieren und mit weiteren öffentlichen Daten anreichern. Studien können dann echte Mittelspannungstopologien nutzen statt synthetischer Modellnetze.",
        title: "Netzkarten georeferenzieren",
      },
      {
        body: "Ergebnisse wann immer möglich unter offenen Lizenzen veröffentlichen, damit andere einen versionierten Datensatz weiterverwenden können, statt wieder bei den Originaldokumenten zu beginnen.",
        title: "Zugänglich machen",
      },
      {
        body: "Eine offene Community, die Daten und Methoden nutzt, prüft und weiterentwickelt.",
        link: { href: github, label: "Auf GitHub mithelfen." },
        title: "Community aufbauen",
      },
    ],
    announcement: {
      href: "/de/blog/2026-11-17-introducing-gridahead",
      label: "Unsere Ankündigung",
    },
    cooperation: "Eine Kooperation des Reiner Lemoine Instituts und Goal100.",
    cooperationKicker: "Kooperation",
    description:
      "Ein Open-Source- und Open-Data-Projekt, das veröffentlichte deutsche Netzausbaupläne in zugängliche, georeferenzierte Datensätze umwandelt.",
    docs: { href: "/de/docs", label: "Dokumentation lesen" },
    facts: [
      {
        body: "80 von 85 Netzbetreibern haben Maßnahmen veröffentlicht. Etwa 20.000 der über 33.000 sind laufend oder geplant. Wo sie liegen, bleibt in der Regel unklar.",
        title: "Zweite Runde, 2026",
      },
      {
        body: "Die meisten Betreiber nutzen nun ein einheitliches Tabellenformat. Die Runde 2024 lag nur als PDF vor. Die Maßnahmen haben weiterhin keine Koordinaten, und die Netzkarten sind weiterhin Bilder in den Berichten.",
        title: "Tabellen, keine Karten",
      },
      {
        body: "Betreiber mit 100.000 oder mehr Kund*innen sowie kleinere mit erheblicher Abregelung von Wind- oder Solarstrom müssen einen Plan auf VNBdigital nach §§ 14d und 14e EnWG veröffentlichen.",
        title: "Alle zwei Jahre",
      },
    ],
    figure:
      "Stilisierte Karte Deutschlands: Sechsecke nach der Dichte der Netzausbaumaßnahmen eingefärbt, überlagert mit einem schematischen Netz aus bestehenden und geplanten Leitungen und Umspannwerken.",
    fundedAfter: " gehostet.",
    fundedBefore:
      "Die Initiative von Goal100 für gridAhead wird gemeinsam von Google.org und der Veolia Stiftung gefördert und von ",
    fundedKicker: "Gefördert von",
    headline: [
      "Netzausbaupläne",
      "in Daten umwandeln.",
      "Offen und georeferenziert.",
    ],
    infrastructure:
      "Die leichtere Nutzbarkeit dieser Pläne steht nicht im Konflikt mit dem Schutz kritischer Infrastruktur. gridAhead arbeitet nur mit Informationen, die Verteilnetzbetreiber bereits veröffentlicht haben.",
    introduction: { href: "/de/docs", label: "Einführung lesen" },
    kicker: "Reiner Lemoine Institut & Goal100",
    lead: "Seit Ende Oktober veröffentlichen die größeren deutschen Verteilnetzbetreiber eine zweite Runde ihrer Netzausbaupläne mit über 33.000 Maßnahmen. Die Daten sind weiterhin schwer nutzbar. gridAhead wandelt diese veröffentlichten Pläne in offene, georeferenzierte Datensätze um.",
    problem: ["Über 33.000 Maßnahmen.", "Als Daten weiterhin schwer nutzbar."],
    problemLead:
      "Neue Wind- und Solaranlagen, Speicher, Wärmepumpen und Ladepunkte können nur so schnell angeschlossen werden, wie die Verteilnetze verstärkt werden. Die Pläne dafür sind öffentlich. Orte, Koordinaten und offene Lizenzen fehlen meist noch.",
    title: "gridAhead — Netzausbaupläne in Daten umwandeln",
    work: [
      "Von veröffentlichten Plänen zu offenen Daten.",
      "Woran gridAhead arbeitet.",
    ],
  },
};
