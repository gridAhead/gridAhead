<picture>
  <source media="(prefers-color-scheme: dark)" srcset="apps/docs/public/logos/gridahead-inverse.svg">
  <img alt="gridAhead" src="apps/docs/public/logos/gridahead.svg" height="36">
</picture>

# gridAhead

Geocode and georeference German distribution grid expansion plans so the public can use them.

<a href="https://reiner-lemoine-institut.de/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/docs/public/logos/reiner-lemoine-institut-inverse.svg">
    <img alt="Reiner Lemoine Institut" src="apps/docs/public/logos/reiner-lemoine-institut.svg" height="40">
  </picture>
</a>
&emsp;
<a href="https://goal100.org/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/docs/public/logos/goal100-inverse.svg">
    <img alt="Goal100" src="apps/docs/public/logos/goal100.svg" height="48">
  </picture>
</a>

Grid expansion is one of the tightest bottlenecks in the energy transition. The plans for the next years are already public: larger distribution system operators have to publish one [every two years](https://www.gesetze-im-internet.de/enwg_2005/__14d.html). They say where the network is expected to grow, which measures are foreseen, and on what timetable. That bears on private and public investment, on research, and on the political debate about where the transition can actually proceed.

The publications do not follow a modern data standard. Places and measures are difficult to compare across operators, difficult to join to other spatial data, and difficult to hand to a model or a map. Publishing a PDF is not the same as publishing data. Despite [broad calls](https://reiner-lemoine-institut.de/offener-brief-an-bnetza-netzdaten-besser-nutzbar-machen/) on the Bundesnetzagentur to make grid data usable, that has not changed.

## What gridAhead is building

1. **Geocode planned expansions.** Bind the places and measures in the plans to coordinates.
2. **Georeference medium voltage maps.** Create the most comprehensive public data of current and future medium voltage grids in Germany.
3. **Make it accessible.** Publish the result so others can keep working with it, instead of starting from the original documents again.

gridAhead is a cooperation of the [Reiner Lemoine Institut](https://reiner-lemoine-institut.de/) and [Goal100](https://goal100.org/). [Google.org](https://www.google.org/) and the [Veolia Stiftung](https://www.stiftung.veolia.de/) co-fund the work.

## Development

Requires Node.js 24+, [pnpm](https://pnpm.io/) and [uv](https://docs.astral.sh/uv/).

```bash
pnpm install
pnpm dev     # all apps
pnpm test
pnpm lint
pnpm build
```

Apps:

- `apps/docs`: project website.
- `apps/nap_tool`: extracts and reviews tables from grid expansion plans. It needs the separate `nap_data` repository (internal GitLab); set `NAP_DATA_DIR` in `apps/nap_tool/.env`. See [apps/nap_tool/README.md](apps/nap_tool/README.md). For live frontend work, run `pnpm --filter nap-tool-ui dev:ui` next to `pnpm dev` and open the Vite URL.

## Co-funded by

<a href="https://www.google.org/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/docs/public/logos/google-org-inverse.svg">
    <img alt="Google.org" src="apps/docs/public/logos/google-org.svg" height="22">
  </picture>
</a>
&emsp;
<a href="https://www.stiftung.veolia.de/">
  <img alt="Veolia Stiftung" src="apps/docs/public/logos/veolia-stiftung.png" height="28">
</a>
