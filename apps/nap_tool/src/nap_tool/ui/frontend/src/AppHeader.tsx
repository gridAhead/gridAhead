// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { locale, setLocale, t } from './i18n'

export type HeaderPage = 'overview' | 'sets' | 'harmonize' | 'result' | 'classify' | 'schema' | 'settings'

type Summary = {
  vnbs: number
  downloaded: number
  extracted: number
  cleaned: number
}

type Props = {
  page: HeaderPage
  setId?: number | null
  schemeId?: number | null
  revision?: number
  beforeNavigate?: (page: HeaderPage) => boolean
}

type Link = { page: HeaderPage; path: string; title: string }

const titles: Record<HeaderPage, string> = {
  overview: t("Overview"),
  sets: t("Sets"),
  harmonize: t("Field harmonization"),
  result: t("Harmonized results"),
  classify: t("Classification"),
  schema: t("Database relationships"),
  settings: t("Settings"),
}

const harmonizePages: HeaderPage[] = ['sets', 'harmonize', 'result']

function Metric({ value, label }: { value?: number; label: string }) {
  return <div className="metric"><strong>{value?.toLocaleString(locale === 'de' ? 'de-DE' : 'en-US') ?? '—'}</strong><span>{label}</span></div>
}

export function AppHeader({ page, schemeId, setId, revision = 0, beforeNavigate }: Props) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const moreMenu = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/overview/summary', { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<Summary> : Promise.reject(new Error(t("Could not load data totals"))))
      .then(setSummary)
      .catch(() => { if (!controller.signal.aborted) setSummary(null) })
    return () => controller.abort()
  }, [revision])

  useEffect(() => {
    const closeMenu = (event: PointerEvent) => {
      if (moreMenu.current?.open && !moreMenu.current.contains(event.target as Node)) moreMenu.current.open = false
    }
    addEventListener('pointerdown', closeMenu)
    return () => removeEventListener('pointerdown', closeMenu)
  }, [])

  const schemeQuery = schemeId ? `?scheme=${schemeId}` : ''
  const resultQuery = setId ? `${schemeQuery || '?'}${schemeQuery ? '&' : ''}set=${setId}` : schemeQuery
  const inHarmonize = harmonizePages.includes(page)
  const links: Link[] = [
    { page: 'overview', path: '/ui/overview', title: titles.overview },
    { page: 'harmonize', path: `/ui/harmonize${schemeQuery}`, title: t("Harmonization") },
    { page: 'classify', path: `/ui/classify${resultQuery}`, title: titles.classify },
    { page: 'settings', path: '/ui/settings', title: titles.settings },
  ]
  const harmonizeLinks: Link[] = [
    { page: 'sets', path: '/ui/harmonize/sets', title: t("Sets") },
    { page: 'harmonize', path: `/ui/harmonize${schemeQuery}`, title: t("Schemes") },
    { page: 'result', path: `/ui/harmonize/result${resultQuery}`, title: t("Results") },
  ]
  const moreLinks: Link[] = [{ page: 'schema', path: '/ui/schema', title: titles.schema }]
  const moreActive = moreLinks.some((link) => link.page === page)

  function navLink(link: Link, active = link.page === page) {
    return <a key={link.page} className={active ? 'active' : undefined} aria-current={link.page === page ? 'page' : undefined} href={link.path} onClick={(event) => { if (link.page !== page && beforeNavigate && !beforeNavigate(link.page)) event.preventDefault() }}>{link.title}</a>
  }

  return <>
    <header className="site-header">
      <div className="site-header-inner">
        <div className="site-header-main">
          <a className="brand" href="/ui/overview" aria-label={t("NAP Tool: Reset and return to overview")}><span className="brand-mark" aria-hidden="true"><span /><span /><span /><span /></span><span className="brand-name">{t("NAP ")}<strong>Tool</strong></span></a>
          <strong className="site-header-title">{titles[page]}</strong>
          <nav className="site-header-nav" aria-label={t("Main navigation")}>
            {links.map((link) => navLink(link, link.page === 'harmonize' ? inHarmonize : link.page === page))}
            <details ref={moreMenu} className={`site-header-more${moreActive ? ' active' : ''}`}>
              <summary>{t("More")}<ChevronDown size={12} /></summary>
              <div className="site-header-more-panel">{moreLinks.map((link) => navLink(link))}</div>
            </details>
          </nav>
          <select className="site-header-language" aria-label={t("Language / Sprache")} value={locale} onChange={(event) => { if (!beforeNavigate || beforeNavigate(page)) setLocale(event.target.value as 'en' | 'de') }}><option value="en">{t("English")}</option><option value="de">{t("Deutsch")}</option></select>
        </div>
        <div className="site-header-metrics" aria-label={t("Data totals")}>
          <Metric value={summary?.vnbs} label={t("DSO")} />
          <Metric value={summary?.downloaded} label={t("Downloaded documents")} />
          <Metric value={summary?.extracted} label={t("Extracted tables")} />
          <Metric value={summary?.cleaned} label={t("Cleaned tables")} />
        </div>
      </div>
    </header>
    {inHarmonize && <nav className="site-subnav" aria-label={t("Harmonization sections")}>{harmonizeLinks.map((link) => navLink(link))}</nav>}
  </>
}
