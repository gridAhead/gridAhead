// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  Download,
  FileText,
  ExternalLink,
  Layers3,
  PanelLeftClose,
  Pencil,
  Plus,
  Search,
  Table2,
  Trash2,
  X,
} from 'lucide-react'
import './styles.css'
import { ExtractReview } from './ExtractReview'
import { CleanReview } from './CleanReview'
import { CleanFilters, cleanFilterLabels, type CleanFilter } from './CleanFilters'
import { HarmonizePage } from './HarmonizePage'
import { HarmonizeResultPage } from './HarmonizeResultPage'
import { ClassifyPage } from './ClassifyPage'
import { SettingsPage } from './SettingsPage'
import { SetsPage } from './SetsPage'
import { useTableTypes } from './tableTypes'
import { SchemaPage } from './SchemaPage'
import { AppHeader } from './AppHeader'
import { locale, startLocalization, t } from './i18n'

type ToolFilter = 'all' | 'docling' | 'llmPDF'
type TableTypeFilter = string
type Scope = 'same' | 'all'
type Stage = 'vnb' | 'document' | 'extract' | 'clean'

type Route = {
  cleanFilter?: CleanFilter
  reviewFilter?: CleanFilter
  vnb?: string
  documentVnb: 'same' | 'all'
  extractScope: Scope
  cleanScope: Scope
  year?: number
  document?: number
  extract?: number
  clean?: number
  tool: ToolFilter
  tableType: TableTypeFilter
  q: string
  view?: 'review' | 'clean-review'
}

type Vnb = {
  id: number
  name: string
  slug: string
  mastr_nr: string | null
  bdew_code: string | null
  document_count: number
  downloaded_count: number
}

function DsoIdentifierEditor({ item, onSaved }: { item: Vnb; onSaved: () => void }) {
  const [mastrNr, setMastrNr] = useState(item.mastr_nr || '')
  const [bdewCode, setBdewCode] = useState(item.bdew_code || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    setSaving(true); setError('')
    try {
      const response = await fetch(`/api/overview/dsos/${item.id}/identifiers`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mastr_nr: mastrNr, bdew_code: bdewCode }),
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(result.detail || t("Failed to save identifiers"))
      onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Failed to save identifiers")) }
    finally { setSaving(false) }
  }

  return <div className="dso-identifiers">
    <label>{t("MaStR number")}<input value={mastrNr} onChange={(event) => setMastrNr(event.target.value)} placeholder={t("Unmatched")} /></label>
    <label>{t("BDEW Code")}<input value={bdewCode} onChange={(event) => setBdewCode(event.target.value)} placeholder={t("Unmatched")} /></label>
    <button type="button" onClick={save} disabled={saving}>{saving ? t("Saving…") : t("Save identifiers")}</button>
    {error && <small role="status">{t(error)}</small>}
  </div>
}

type Document = {
  id: number
  title: string
  year: number | null
  dso_slug: string
  vnb_name: string
  version: string | null
  source: string
  is_selected: number
  is_downloaded: number
  file_type: string | null
  extract_count: number
  created_at: string
  updated_at: string
}

function DocumentYearEditor({ item, onSaved }: { item: Document; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [year, setYear] = useState(item.year?.toString() || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setYear(item.year?.toString() || '') }, [item.year, item.updated_at])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true); setError('')
    try {
      const response = await fetch(`/api/overview/documents/${item.id}/year`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nap_year: year === '' ? null : Number(year), expected_updated_at: item.updated_at }),
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : t("Could not save year"))
      setEditing(false); onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not save year")) }
    finally { setSaving(false) }
  }

  if (!editing) return <button type="button" className="document-year-edit" onClick={() => { setError(''); setEditing(true) }}><Pencil size={13} />{t("Edit year")}</button>
  return <form className="document-year-editor" onSubmit={save}>
    <label>{t("NAP round")}<input aria-label={t("NAP round for document {0}", item.id)} type="number" min={2000} max={2100} step={1} value={year} placeholder={t("Unknown")} onChange={event => setYear(event.target.value)} disabled={saving} /></label>
    <button type="submit" disabled={saving}>{saving ? t("Saving…") : t("Save")}</button>
    <button type="button" disabled={saving} onClick={() => { setYear(item.year?.toString() || ''); setEditing(false) }}>{t("Cancel")}</button>
    {error && <small role="alert">{t(error)}</small>}
  </form>
}

type ExtractTable = {
  id: number
  document_id: number
  document_title: string
  dso_slug: string
  vnb_name: string
  tool: string
  table_number: number
  first_page: number | null
  page_count: number
  title: string | null
  is_selected: boolean
  table_type: number | null
  is_confirmed: boolean
  has_review_file: boolean
  is_archived: boolean
  is_stale: boolean
  clean_count: number
  created_at: string
}

type CleanTable = {
  id: number
  extract_table_id: number
  title: string
  is_selected: boolean
  is_confirmed: boolean
  is_legacy: boolean
  is_stale: boolean
  has_review_file: boolean
  review_is_stale: boolean
  unresolved_count: number
  manual_count: number
  unresolved_modified_count: number
  pending_count: number
  document_id: number
  document_title: string
  dso_slug: string
  vnb_name: string
  tool: string
  table_number: number
  created_at: string
  updated_at: string
}

function parseRoute(): Route {
  const params = new URLSearchParams(window.location.search)
  const tool = params.get('tool')
  const measures = params.get('measures')
  const tableType = params.get('table_type')
  const legacyCleanFilter = params.get('clean_filter')?.split(',')[0]
  const cleanFilter = legacyCleanFilter && legacyCleanFilter in cleanFilterLabels ? legacyCleanFilter as CleanFilter : undefined
  const reviewFilterParam = params.get('review_filter')
  const reviewFilter = reviewFilterParam && reviewFilterParam in cleanFilterLabels ? reviewFilterParam as CleanFilter : undefined
  const asId = (value: string | null) => {
    const parsed = Number(value)
    return value && Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
  }
  return {
    vnb: params.get('vnb') || undefined,
    documentVnb: params.get('document_vnb') === 'all' || !params.get('vnb') ? 'all' : 'same',
    extractScope: params.get('extract_scope') === 'all' ? 'all' : 'same',
    cleanScope: params.get('clean_scope') === 'all' ? 'all' : 'same',
    year: /^20\d{2}$/.test(params.get('year') || '') ? Number(params.get('year')) : undefined,
    document: asId(params.get('document')),
    extract: asId(params.get('extract')),
    clean: asId(params.get('clean')),
    tool: tool === 'docling' || tool === 'llmPDF' ? tool : 'all',
    tableType: !!tableType && /^[1-9]\d*$/.test(tableType) || tableType === 'unclassified' || tableType === 'non_measures'
      ? tableType : measures === 'yes' ? '1' : measures === 'no' ? 'non_measures' : 'all',
    q: params.get('q') || '',
    cleanFilter,
    reviewFilter,
    view: params.get('view') === 'review' || params.get('view') === 'clean-review'
      ? params.get('view') as Route['view'] : undefined,
  }
}

function stageForRoute(route: Route): Stage {
  if (route.extract) return 'clean'
  if (route.cleanScope === 'all') return 'clean'
  if (route.document || route.extractScope === 'all') return 'extract'
  if (route.vnb || route.year || route.documentVnb === 'all') return 'document'
  return 'vnb'
}

function useResource<T>(path: string | null): {
  data: T | null
  loading: boolean
  error: string | null
} {
  const [data, setData] = useState<T | null>(null)
  const [loadedPath, setLoadedPath] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!path) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setData(null)
    fetch(path, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(t("Failed to load data({0})", response.status))
        return response.json() as Promise<T>
      })
      .then((value) => {
        setLoadedPath(path)
        setData(value)
        setLoading(false)
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setLoadedPath(path)
        setError(reason instanceof Error ? reason.message : t("Failed to load data"))
        setLoading(false)
      })
    return () => controller.abort()
  }, [path])

  return { data: loadedPath === path ? data : null, loading: Boolean(path) && (loading || loadedPath !== path), error: loadedPath === path ? error : null }
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return t("Unknown date")
  return new Intl.DateTimeFormat(locale === 'de' ? 'de-DE' : 'en-US', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

function readCollapsed(): Stage[] {
  try {
    const value = JSON.parse(localStorage.getItem('nap-overview-collapsed') || '[]') as unknown
    if (!Array.isArray(value)) return []
    return value.filter((item): item is Stage => item === 'vnb' || item === 'document' || item === 'extract')
  } catch {
    return []
  }
}

function App() {
  const { types: tableTypes, error: tableTypesError } = useTableTypes()
  useEffect(() => { document.title = locale === 'de' ? 'NAP Tool · Datenübersicht' : t("NAP Tool · Overview") }, [])
  const [route, setRoute] = useState<Route>(parseRoute)
  const [collapsed, setCollapsed] = useState<Stage[]>(readCollapsed)
  const [mobileStage, setMobileStage] = useState<Stage>(() => stageForRoute(parseRoute()))
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 700px)').matches)
  const [reviewRevision, setReviewRevision] = useState(0)
  const [dsoRevision, setDsoRevision] = useState(0)
  const [documentRevision, setDocumentRevision] = useState(0)
  const [cleanBusy, setCleanBusy] = useState(false)
  const [cleanError, setCleanError] = useState('')

  useEffect(() => {
    const media = window.matchMedia('(max-width: 700px)')
    const onChange = () => setIsMobile(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const onPopState = () => {
      const next = parseRoute()
      setRoute(next)
      setMobileStage(stageForRoute(next))
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function navigate(patch: Partial<Route>, mode: 'push' | 'replace' = 'push') {
    const next: Route = { ...parseRoute(), ...patch }
    const params = new URLSearchParams()
    if (next.vnb) params.set('vnb', next.vnb)
    if (next.documentVnb === 'all') params.set('document_vnb', 'all')
    if (next.extractScope === 'all') params.set('extract_scope', 'all')
    if (next.cleanScope === 'all') params.set('clean_scope', 'all')
    if (next.year) params.set('year', String(next.year))
    if (next.document) params.set('document', String(next.document))
    if (next.extract) params.set('extract', String(next.extract))
    if (next.clean) params.set('clean', String(next.clean))
    if (next.cleanFilter) params.set('clean_filter', next.cleanFilter)
    if (next.reviewFilter) params.set('review_filter', next.reviewFilter)
    if (next.tool !== 'all') params.set('tool', next.tool)
    if (next.tableType !== 'all') params.set('table_type', next.tableType)
    if (next.q) params.set('q', next.q)
    if (next.view) params.set('view', next.view)
    const url = `/ui/overview${params.size ? `?${params.toString()}` : ''}`
    window.history[mode === 'push' ? 'pushState' : 'replaceState']({}, '', url)
    setRoute(next)
  }

  function selectVnb(slug: string) {
    navigate({ vnb: slug, documentVnb: 'same', document: undefined, extract: undefined, clean: undefined, view: undefined })
    setMobileStage('document')
  }

  function selectDocument(id: number) {
    navigate({ document: id, extract: undefined, clean: undefined, view: undefined })
    setMobileStage('extract')
  }

  function selectExtract(item: ExtractTable) {
    navigate({ vnb: item.dso_slug, documentVnb: 'same', document: item.document_id,
      extract: item.id, clean: undefined, view: route.view === 'review' ? 'review' : undefined })
    if (route.view !== 'review') setMobileStage('clean')
  }

  async function createCleanVersion() {
    if (!route.extract || cleanBusy) return
    setCleanBusy(true); setCleanError('')
    try {
      const response = await fetch('/api/clean-versions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ extract_id: route.extract }),
      })
      const result = await response.json() as { id?: number; detail?: string }
      if (!response.ok || !result.id) throw new Error(result.detail || t("Could not create cleaned version"))
      setReviewRevision((value) => value + 1)
      navigate({ clean: result.id, view: 'clean-review' })
    } catch (reason) { setCleanError(reason instanceof Error ? reason.message : t("Could not create cleaned version")) }
    finally { setCleanBusy(false) }
  }

  async function renameCleanVersion(item: CleanTable) {
    const title = window.prompt(t("Cleaned version name"), item.title)?.trim()
    if (!title || title === item.title) return
    try {
      const response = await fetch(`/api/clean-review/${item.id}/metadata`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(result.detail || t("Rename failed"))
      setReviewRevision((value) => value + 1)
    } catch (reason) { setCleanError(reason instanceof Error ? reason.message : t("Rename failed")) }
  }

  async function selectCleanVersion(item: CleanTable) {
    if (item.is_selected) return
    setCleanError('')
    try {
      const response = await fetch(`/api/clean-review/${item.id}/metadata`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_selected: true }),
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(result.detail || t("Could not select this version"))
      setReviewRevision((value) => value + 1)
    } catch (reason) { setCleanError(reason instanceof Error ? reason.message : t("Could not select this version")) }
  }

  async function deleteCleanVersion(item: CleanTable) {
    if (cleanBusy || !window.confirm(t("Delete “{0}”? This cannot be undone.", item.title))) return
    setCleanBusy(true); setCleanError('')
    try {
      const response = await fetch(`/api/clean-versions/${item.id}`, { method: 'DELETE' })
      const result = await response.json() as { selected_id?: number | null; detail?: string }
      if (!response.ok) throw new Error(result.detail || t("Failed to delete cleaned version"))
      if (route.clean === item.id) navigate({ clean: result.selected_id ?? undefined, view: undefined })
      setReviewRevision((value) => value + 1)
    } catch (reason) { setCleanError(reason instanceof Error ? reason.message : t("Failed to delete cleaned version")) }
    finally { setCleanBusy(false) }
  }

  function toggleCollapsed(stage: Stage) {
    const next = collapsed.includes(stage)
      ? collapsed.filter((item) => item !== stage)
      : [...collapsed, stage]
    setCollapsed(next)
    localStorage.setItem('nap-overview-collapsed', JSON.stringify(next))
  }

  const vnbs = useResource<Vnb[]>(`/api/overview/dsos?revision=${dsoRevision}`)
  const documents = useResource<Document[]>(`/api/overview/documents?revision=${documentRevision}`)
  const extracts = useResource<ExtractTable[]>(
    route.extractScope === 'all' || route.document
      ? `/api/overview/extract-tables?${route.extractScope === 'same' && route.document ? `document_id=${route.document}&` : ''}tool=${route.tool}&table_type=${route.tableType}&revision=${reviewRevision}`
      : null,
  )
  const allCleanTables = route.cleanScope === 'all'
  const cleanQuery = new URLSearchParams({ revision: String(reviewRevision) })
  if (!allCleanTables && route.extract) cleanQuery.set('extract_id', String(route.extract))
  if (route.cleanFilter) cleanQuery.set(route.cleanFilter, 'true')
  const cleans = useResource<CleanTable[]>(
    allCleanTables || route.extract ? `/api/overview/clean-tables?${cleanQuery}` : null,
  )
  function changeCleanFilter(value: CleanFilter | null) {
    navigate({ cleanFilter: value ?? undefined })
  }
  function changeReviewFilter(value: CleanFilter[]) {
    navigate({ reviewFilter: value[0] })
  }
  function openClean(item: CleanTable, view?: Route['view']) {
    navigate({ vnb: item.dso_slug, documentVnb: 'same', document: item.document_id, extract: item.extract_table_id, clean: item.id, view })
  }

  useEffect(() => {
    if (vnbs.data && route.vnb && !vnbs.data.some((item) => item.slug === route.vnb)) {
      navigate({ vnb: undefined, documentVnb: 'all', document: undefined, extract: undefined, clean: undefined, view: undefined }, 'replace')
    }
  }, [vnbs.data, route.vnb])

  useEffect(() => {
    if (documents.data && route.document && !documents.data.some((item) => item.id === route.document)) {
      navigate({ document: undefined, extract: undefined, clean: undefined, view: undefined }, 'replace')
    }
  }, [documents.data, route.document])

  const visibleVnbs = useMemo(() => {
    const term = route.q.trim().toLocaleLowerCase('de-DE')
    if (!term) return vnbs.data || []
    return (vnbs.data || []).filter((item) =>
      `${item.name} ${item.slug}`.toLocaleLowerCase('de-DE').includes(term),
    )
  }, [vnbs.data, route.q])

  const documentYears = useMemo(() => Array.from(new Set(
    (documents.data || []).map((item) => item.year).filter((year): year is number => year !== null),
  )).sort((left, right) => right - left), [documents.data])
  const visibleDocuments = useMemo(() => (documents.data || []).filter((item) =>
    (route.documentVnb === 'all' || !route.vnb || item.dso_slug === route.vnb) && (!route.year || item.year === route.year),
  ), [documents.data, route.documentVnb, route.vnb, route.year])

  const chosenExtract = extracts.data?.find((item) => item.id === route.extract)
  const extractReviewMode = route.view === 'review' && Boolean(route.extract)
  const cleanReviewMode = route.view === 'clean-review' && Boolean(route.clean)
  const reviewMode = extractReviewMode || cleanReviewMode
  const stages: { key: Stage; label: string; count: number | string }[] = [
    { key: 'vnb', label: t("DSO"), count: visibleVnbs.length },
    { key: 'document', label: t("Documents"), count: documents.data ? visibleDocuments.length : '—' },
    { key: 'extract', label: t("Extracted tables"), count: extracts.data?.length ?? '—' },
    { key: 'clean', label: t("Cleaned tables"), count: cleans.data?.length ?? '—' },
  ]

  return (
    <div className="app-shell">
      <AppHeader page="overview" revision={reviewRevision} />

      <main className={`main-content ${reviewMode ? 'has-review' : ''}`}>
        <nav className="mobile-steps" aria-label={t("Browse stages")}>
          {stages.map((stage, index) => (
            <button
              key={stage.key}
              className={`mobile-step ${mobileStage === stage.key ? 'active' : ''}`}
              onClick={() => setMobileStage(stage.key)}
              type="button"
            >
              <span>{String(index + 1).padStart(2, '0')}</span> {stage.label}
            </button>
          ))}
        </nav>

        <div className={`explorer ${reviewMode ? 'review-mode' : ''}`} data-mobile-stage={mobileStage}>
          <Pane
            stage="vnb" number="01" title={t("DSO")} subtitle="DSO"
            icon={<Database size={19} />} count={visibleVnbs.length}
            collapsed={!isMobile && (reviewMode || collapsed.includes('vnb'))} onToggle={() => reviewMode ? navigate({ view: undefined }) : toggleCollapsed('vnb')}
          >
            <div className="search-wrap">
              <Search size={17} strokeWidth={2} />
              <input
                aria-label={t("Search DSOs")}
                placeholder={t("Search name or identifier…")}
                value={route.q}
                onChange={(event) => navigate({ q: event.target.value }, 'replace')}
              />
              {route.q && <button className="clear-search" aria-label={t("Clear search")} onClick={() => navigate({ q: '' }, 'replace')}><X size={15} /></button>}
            </div>
            <PaneIntro>{t("Select a DSO, or filter documents by NAP round across all DSOs.")}</PaneIntro>
            <ListState loading={vnbs.loading} error={t(vnbs.error)} empty={visibleVnbs.length === 0} emptyText={route.q ? t("No matching DSOs") : t("No DSOs yet")}>
              <div className="item-list">
                {visibleVnbs.map((item) => (<React.Fragment key={item.id}>
                  <button key={item.id} className={`item-card vnb-card ${route.vnb === item.slug ? 'selected' : ''}`} onClick={() => selectVnb(item.slug)} type="button" aria-pressed={route.vnb === item.slug}>
                    <span className="item-top"><span className="item-title">{item.name}</span><ChevronRight size={17} className="item-arrow" /></span>
                    <span className="item-slug">{item.slug}</span>
                    <span className="item-meta"><span><FileText size={13} /> {item.document_count} {t("  documents")}</span><span>{item.downloaded_count} {t("  downloaded")}</span></span>
                  </button>
                  {route.vnb === item.slug && <DsoIdentifierEditor key={item.id} item={item} onSaved={() => setDsoRevision((value) => value + 1)} />}
                </React.Fragment>))}
              </div>
            </ListState>
          </Pane>

          <Pane
            stage="document" number="02" title={t("Documents")} subtitle="DOCUMENT"
            icon={<FileText size={19} />} count={documents.data ? visibleDocuments.length : null}
            collapsed={!isMobile && (reviewMode || collapsed.includes('document'))} onToggle={() => reviewMode ? navigate({ view: undefined }) : toggleCollapsed('document')}
          >
            <div className="document-filters">
              <label>
                <span>{t("DSO")}</span>
                <select aria-label={t("Filter documents by DSO")} value={route.documentVnb} onChange={(event) => navigate({ documentVnb: event.target.value as Route['documentVnb'], document: undefined, extract: undefined, clean: undefined, view: undefined })}>
                  <option value="same" disabled={!route.vnb}>{t("Same as left")}</option>
                  <option value="all">{t("All DSOs")}</option>
                </select>
              </label>
              <label>
                <span>{t("Year")}</span>
                <select aria-label={t("Filter documents by year")} value={route.year || ''} onChange={(event) => navigate({ year: event.target.value ? Number(event.target.value) : undefined, document: undefined, extract: undefined, clean: undefined, view: undefined })}>
                  <option value="">{t("All years")}</option>
                  {documentYears.map((year) => <option key={year} value={year}>{year} {t(" ")}</option>)}
                </select>
              </label>
            </div>
            <PaneIntro>{t("Keep different versions and mark the PDF currently in use.")}</PaneIntro>
            <ListState loading={documents.loading} error={t(documents.error)} empty={visibleDocuments.length === 0} emptyText={t("No documents match the filters")}>
              <div className="item-list">
                {visibleDocuments.map((item) => (
                  <div key={item.id} className={`item-card document-card ${route.document === item.id ? 'selected' : ''}`}>
                    <button className="document-card-select" onClick={() => selectDocument(item.id)} type="button" aria-pressed={route.document === item.id}>
                      <span className="item-top"><span className="item-title file-title" title={item.title}>{item.title}</span><ChevronRight size={17} className="item-arrow" /></span>
                      {(route.documentVnb === 'all' || !route.vnb) && <span className="document-vnb-name">{item.vnb_name}</span>}
                      <span className="badge-line">
                        <StatusBadge tone={item.is_downloaded ? 'success' : 'warning'}>{item.is_downloaded ? t("Downloaded") : t("Pending download")}</StatusBadge>
                        {!item.is_downloaded ? (
                          <StatusBadge tone="neutral">{t("Candidate document")}</StatusBadge>
                        ) : item.is_selected ? (
                          <StatusBadge tone="blue">{t("Current selection")}</StatusBadge>
                        ) : (
                          <StatusBadge tone="neutral">{t("Previous version")}</StatusBadge>
                        )}
                      </span>
                    </button>
                    <div className="document-card-bottom">
                      <span className="item-meta"><span>{t("Document #")}{item.id}</span><span>{item.year ? t("{0} ", item.year) : t("Year unknown")}</span><span>{item.extract_count} {t("  extracted tables")}</span></span>
                      {Boolean(item.is_downloaded) && item.file_type === 'pdf' && <a className="document-open-pdf" href={`/api/overview/documents/${item.id}/pdf`} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> {t(" Open PDF")}</a>}
                      {Boolean(item.is_downloaded) && ['xlsx', 'xlsm', 'xls'].includes(item.file_type || '') && <a className="document-open-pdf" href={`/api/overview/documents/${item.id}/table`} download><Download size={13} /> {t(" Open table")}</a>}
                      {Boolean(item.is_downloaded) && ['md', 'markdown', 'txt'].includes(item.file_type || '') && <a className="document-open-pdf" href={`/api/overview/documents/${item.id}/text`} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> {t(" Open Markdown")}</a>}
                    </div>
                    <DocumentYearEditor item={item} onSaved={() => setDocumentRevision(value => value + 1)} />
                  </div>
                ))}
              </div>
            </ListState>
          </Pane>

          <Pane
            stage="extract" number="03" title={t("Extracted tables")} subtitle="EXTRACTED TABLE"
            icon={<Table2 size={19} />} count={extracts.data?.length ?? null}
            collapsed={!isMobile && (cleanReviewMode || collapsed.includes('extract'))} onToggle={() => cleanReviewMode ? navigate({ view: undefined }) : toggleCollapsed('extract')}
            headerAction={<span className="extract-scope-select filter-select-wrap">
              <select aria-label={t("Extracted table scope")} value={route.extractScope} onChange={(event) => navigate({ extractScope: event.target.value as Scope })}>
                <option value="same" disabled={!route.document}>{t("Same as left")}</option>
                <option value="all">{t("All")}</option>
              </select><ChevronDown size={12} aria-hidden="true" />
            </span>}
          >
            <div className="filter-block">
              <label className="filter-field">
                <span className="filter-label">{t("Extraction tool")}</span>
                <span className="filter-select-wrap">
                  <select
                    aria-label={t("Filter by extraction tool")}
                    value={route.tool}
                    onChange={(event) => navigate({ tool: event.target.value as ToolFilter })}
                  >
                    <option value="all">{t("All tools")}</option>
                    <option value="docling">{t("Docling")}</option>
                    <option value="llmPDF">{t("llmPDF")}</option>
                  </select>
                  <ChevronDown size={14} aria-hidden="true" />
                </span>
              </label>
              <label className="filter-field">
                <span className="filter-label">{t("Table type")}</span>
                <span className="filter-select-wrap">
                  <select
                    aria-label={t("Filter by table type")}
                    title={t(tableTypesError || undefined)}
                    value={route.tableType}
                    onChange={(event) => navigate({ tableType: event.target.value as TableTypeFilter })}
                  >
                    <option value="all">{t("All tables")}</option>
                    {tableTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                    <option value="unclassified">{t("No table type")}</option>
                    <option value="non_measures">{t("Other table types")}</option>
                  </select>
                  <ChevronDown size={14} aria-hidden="true" />
                </span>
              </label>
            </div>
            {route.extractScope === 'same' && !route.document ? <WaitingState icon={<FileText size={27} />} title={t("Select a document")} detail={t("Select a document or choose all documents to see extracted tables here.")} /> :
              <ListState loading={extracts.loading} error={t(extracts.error)} empty={extracts.data?.length === 0} emptyText={t("No extracted tables match the filters")}>
                <div className="item-list">
                  {extracts.data?.map((item) => (
                    <div key={item.id} className={`item-card extract-card ${route.extract === item.id ? 'selected' : ''}`}>
                      <button className="extract-select" onClick={() => selectExtract(item)} type="button" aria-pressed={route.extract === item.id}>
                      <span className="item-top"><span className="table-index">{t("tables ")}{String(item.table_number).padStart(2, '0')}</span><ChevronRight size={17} className="item-arrow" /></span>
                      {route.extractScope === 'all' && <span className="extract-source">{item.vnb_name} · {item.document_title}</span>}
                      {item.title && <span className="extract-title" title={item.title}>{item.title}</span>}
                      <span className="badge-line">
                        <StatusBadge tone="blue">{item.tool}</StatusBadge>
                        {item.table_type !== null && <StatusBadge tone="mint">{tableTypes.find((type) => type.id === item.table_type)?.name ?? t("Type #{0}", item.table_type)}</StatusBadge>}
                        {item.is_archived && <StatusBadge tone="neutral">{t("Archived")}</StatusBadge>}
                      </span>
                      </button>
                      <div className="extract-card-footer">
                        <span className="item-meta"><span>{item.first_page ? t(" {0}  page", item.first_page) : t("Page unknown")}</span><span>{item.is_stale ? t("Review source changed") : item.is_confirmed ? t("Extraction reviewed") : t("Pending review")}</span><span>{item.clean_count} {t("  cleaned versions")}</span></span>
                        <button className="extract-review-button" type="button" onClick={() => navigate({ vnb: item.dso_slug, documentVnb: 'same', document: item.document_id, extract: item.id, clean: undefined, view: 'review' })}>{t("Manual review ")}<ArrowRight size={13} /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </ListState>}
          </Pane>

          {extractReviewMode && route.extract && <ExtractReview
            extractId={route.extract}
            onClose={() => navigate({ view: undefined })}
            onSaved={() => setReviewRevision((value) => value + 1)}
          />}

          <Pane
            stage="clean" number="04" title={t("Cleaned tables")} subtitle="CLEAN TABLE"
            icon={<Layers3 size={19} />} count={cleans.data?.length ?? null}
            collapsed={!isMobile && extractReviewMode} onToggle={() => navigate({ view: undefined })}
          >
            <div className="filter-block clean-list-filters">
              <label className="filter-field"><span className="filter-label">{t("Extracted tables")}</span><span className="filter-select-wrap">
                <select aria-label={t("Cleaned table scope")} value={route.cleanScope} onChange={(event) => navigate({ cleanScope: event.target.value as Scope })}>
                  <option value="same" disabled={!route.extract}>{t("Same as left")}</option>
                  <option value="all">{t("All extracted tables")}</option>
                </select><ChevronDown size={14} aria-hidden="true" />
              </span></label>
              <CleanFilters value={route.cleanFilter ?? null} onChange={changeCleanFilter} />
            </div>
            <div className="clean-list-toolbar"><button type="button" onClick={createCleanVersion} disabled={!route.extract || cleanBusy}><Plus size={14} /> {cleanBusy ? t("Creating…") : t("New version")}</button></div>
            {cleanError && <div className="review-feedback review-error" role="status">{t(cleanError)}</div>}
            <PaneIntro>{t("Each version stores its rules, automatic output and manual review separately.")}</PaneIntro>
            {!route.extract && !allCleanTables ? <WaitingState icon={<Table2 size={27} />} title={t("Select an extracted table")} detail={t("Select an extracted table or choose all extracted tables to see cleaned versions here.")} /> :
              <ListState loading={cleans.loading} error={t(cleans.error)} empty={cleans.data?.length === 0} emptyText={allCleanTables || route.cleanFilter ? t("No cleaned tables match the filters.") : t("No cleaned versions yet. A new version will use the {0} as input.", chosenExtract?.has_review_file ? t("reviewed extracted table") : t("automatic extracted table"))}>
                <div className="item-list">
                  {cleans.data?.map((item) => (
                    <div key={item.id} className={`item-card clean-card ${route.clean === item.id ? 'selected' : ''}`}>
                    <button className="extract-select" onClick={() => openClean(item, cleanReviewMode ? 'clean-review' : undefined)} type="button" aria-pressed={route.clean === item.id}>
                      <span className="item-top"><span className="table-index">{item.title} <span className="result-id">#{item.id}</span></span><ChevronRight size={17} className="item-arrow" /></span>
                      {allCleanTables && <span className="item-meta">{item.vnb_name} · {item.document_title} · {item.tool} {t(" · Extracted table #")}{item.extract_table_id}</span>}
                      <span className="badge-line">
                        {item.is_legacy && <StatusBadge tone="orange">{t("Migrated from old workflow")}</StatusBadge>}
                        <StatusBadge tone={item.is_confirmed ? 'success' : 'warning'}>{item.is_legacy ? item.is_confirmed ? t("Old workflow approved") : t("Old workflow not approved") : item.is_confirmed ? t("Cleaning reviewed") : t("Pending review")}</StatusBadge>
                        {item.is_selected && <StatusBadge tone="blue">{t("Current selection")}</StatusBadge>}
                      </span>
                      <span className="item-meta"><span>{item.manual_count} {t("  manual edits · ")}{item.unresolved_modified_count} {t("  manual edits after unresolved values · ")}{item.pending_count} {t("  unresolved")}</span><span>{t("Updated ")}{formatDate(item.updated_at)}</span>{item.is_stale && <span className="stale-text"><CircleAlert size={13} /> {t(" Source changed")}</span>}{item.review_is_stale && <span className="stale-text">{t("Review again")}</span>}</span>
                    </button>
                    <div className="clean-card-actions"><button type="button" onClick={() => openClean(item, 'clean-review')}>{t("Manual review ")}<ArrowRight size={13} /></button><button type="button" onClick={() => void renameCleanVersion(item)} aria-label={`${locale === 'de' ? 'Umbenennen' : t("Rename")}: ${item.title}`}><Pencil size={13} /> {t(" Rename")}</button>{!item.is_selected && <button type="button" onClick={() => void selectCleanVersion(item)}>{t("Set as current")}</button>}<button className="clean-delete-button" type="button" onClick={() => void deleteCleanVersion(item)} disabled={cleanBusy} aria-label={`${locale === 'de' ? 'Löschen' : t("Delete")}: ${item.title}`}><Trash2 size={13} /> {t(" Delete")}</button></div>
                    </div>
                  ))}
                </div>
              </ListState>}
          </Pane>
          {cleanReviewMode && route.clean && <CleanReview filters={route.reviewFilter ? [route.reviewFilter] : []} onFiltersChange={changeReviewFilter} cleanId={route.clean} onClose={() => navigate({ view: undefined })} onSaved={() => setReviewRevision((value) => value + 1)} />}
        </div>

        <footer className="footer"><span>{t("NAP TOOL · Overview")}</span><span>{t("Files are stored in nap_data; records are linked in SQLite")}</span></footer>
      </main>
    </div>
  )
}

function Pane({ stage, number, title, subtitle, icon, count, collapsed = false, onToggle, headerAction, children }: {
  stage: Stage
  number: string
  title: string
  subtitle: string
  icon: React.ReactNode
  count: number | null
  collapsed?: boolean
  onToggle?: () => void
  headerAction?: React.ReactNode
  children: React.ReactNode
}) {
  return <section className={`pane pane-${stage} ${collapsed ? 'collapsed' : ''}`} aria-label={title}>
    {collapsed ? <button className="collapsed-tab" onClick={onToggle} type="button" aria-label={t("Expand {0}", title)}><ChevronRight size={19} /><span>{title}</span><small>{count ?? '—'}</small></button> : <>
      <div className="pane-header">
        <div className="pane-header-main"><span className="pane-number">{number}</span><span className="pane-icon">{icon}</span><div><div className="pane-title">{title}<span className="pane-count">{count ?? '—'}</span></div><div className="pane-subtitle">{subtitle}</div></div></div>
        <div className="pane-header-actions">
          {headerAction}
          {onToggle && <button className="collapse-button" onClick={onToggle} type="button" aria-label={t("Collapse {0}", title)} title={t("Collapse {0}", title)}><PanelLeftClose size={18} /></button>}
        </div>
      </div>
      <div className="pane-body">{children}</div>
    </>}
  </section>
}

function PaneIntro({ children }: { children: React.ReactNode }) {
  return <p className="pane-intro">{children}</p>
}

function StatusBadge({ children, tone }: { children: React.ReactNode; tone: 'success' | 'warning' | 'blue' | 'neutral' | 'mint' | 'orange' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

function WaitingState({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return <div className="waiting-state"><span className="waiting-icon">{icon}</span><strong>{title}</strong><span>{detail}</span></div>
}

function ListState({ loading, error, empty, emptyText, children }: { loading: boolean; error: string | null; empty: boolean; emptyText: string; children: React.ReactNode }) {
  if (loading) return <div className="list-message"><span className="spinner" /> {t(" Loading data…")}</div>
  if (error) return <div className="list-message error"><CircleAlert size={18} /> {t(error)}</div>
  if (empty) return <div className="list-message empty"><Clock3 size={19} /> {emptyText}</div>
  return <>{children}</>
}

startLocalization()
const pages: Record<string, React.ComponentType> = {
  '/ui/classify': ClassifyPage,
  '/ui/settings': SettingsPage,
  '/ui/schema': SchemaPage,
  '/ui/harmonize': HarmonizePage,
  '/ui/harmonize/sets': SetsPage,
  '/ui/harmonize/result': HarmonizeResultPage,
}
const Page = pages[location.pathname] ?? App

// Sets used to live under Settings; keep old bookmarks working.
if (location.pathname === '/ui/settings' && new URLSearchParams(location.search).get('category') === 'harmonization') {
  location.replace('/ui/harmonize/sets')
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Page /></React.StrictMode>,
)
