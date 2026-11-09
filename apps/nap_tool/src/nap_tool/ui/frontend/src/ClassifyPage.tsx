// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ChevronDown, Download, ListFilter, RotateCw, Search, SlidersHorizontal, X } from 'lucide-react'
import { SourceDialog } from './HarmonizeResultPage'
import { useHarmonizeSets } from './harmonizeSets'
import { AppHeader } from './AppHeader'

type Scheme = { initial_set_id: number | null; id: number; name: string; has_output: boolean; output_is_stale: boolean; fields: { key: string; title: string }[] }
type Metric = { name: string; dso: string; value: number | null; empty_share?: number | null; empty_count?: number; row_count?: number; expected?: string; status: string }
type Report = { nap_round: number; status: string; rows: number; record_types: Record<string, number>; coverage: Record<string, number>; metrics: Metric[]; [key: string]: unknown }
type Status = { has_output: boolean; stale: boolean; reason: string; report: Report | null }
type Preview = { header: string[]; derived: string[]; rows: string[][]; total_rows: number; page_size: number; options: Record<string, string[]> }

async function request<T>(url: string, method = 'GET', signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { method, signal })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || t("Request failed"))
  return payload as T
}

export function ClassifyPage() {
  const { sets, loading: setsLoading, error: setsError } = useHarmonizeSets()
  const [setId, setSetId] = useState(Number(new URLSearchParams(location.search).get('set')) || 0)
  const setQuery = setId ? `?set_id=${setId}` : ''
  const [schemes, setSchemes] = useState<Scheme[]>([])
  const [schemeId, setSchemeId] = useState(Number(new URLSearchParams(location.search).get('scheme')) || 0)
  const [scheme, setScheme] = useState<Scheme | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [tab, setTab] = useState('data')
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [columns, setColumns] = useState<string[] | null>(null)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [source, setSource] = useState<string | null>(null)
  const [rowDetails, setRowDetails] = useState<string[] | null>(null)
  const resultUrl = `/ui/harmonize/result?scheme=${schemeId}${setId ? `&set=${setId}` : ''}`
  const report = status?.report

  useEffect(() => {
    document.title = t("NAP Tool · Classification")
    request<Scheme[]>('/api/harmonize/schemes').then(items => {
      setSchemes(items)
      const selected = items.find(item => item.id === schemeId) || items[0]
      if (selected) { setSchemeId(selected.id); if (!setId) setSetId(selected.initial_set_id || 0) }
    }).catch(reason => setError(String(reason.message)))
  }, []) // Initial URL chooses the scheme; selection changes below.

  useEffect(() => {
    if (!setsLoading && setId && !sets.some(item => item.id === setId && item.is_grid_measure)) setSetId(0)
  }, [sets, setsLoading, setId])

  useEffect(() => {
    if (schemeId) history.replaceState(null, '', `/ui/classify?scheme=${schemeId}${setId ? `&set=${setId}` : ''}`)
    if (!schemeId || !setId || setsLoading || !sets.some(item => item.id === setId && item.is_grid_measure)) { setStatus(null); setScheme(null); setPreview(null); return }
    const controller = new AbortController()
    setStatus(null); setScheme(null); setPreview(null); setError(''); setColumns(null)
    setRowDetails(null); setSource(null)
    Promise.all([
      request<Scheme>(`/api/harmonize/schemes/${schemeId}${setQuery}`, 'GET', controller.signal),
      request<Status>(`/api/classify/schemes/${schemeId}${setQuery}`, 'GET', controller.signal),
    ]).then(([item, result]) => { setScheme(item); setStatus(result) })
      .catch(reason => { if (reason.name !== 'AbortError') setError(reason.message) })
    return () => controller.abort()
  }, [schemeId, setId, revision, setsLoading, sets])

  // Keep the previous page while filtering or paging so header filter inputs stay mounted and focused.
  useEffect(() => { setPreview(null) }, [schemeId, setId, status, tab])

  useEffect(() => {
    setRowDetails(null)
    if (!status?.has_output || tab === 'report') return
    const controller = new AbortController()
    const query = new URLSearchParams({ ...filters, set_id: String(setId), page: String(page), view: tab })
    request<Preview>(`/api/classify/schemes/${schemeId}/preview?${query}`, 'GET', controller.signal)
      .then(setPreview).catch(reason => { if (reason.name !== 'AbortError') setError(reason.message) })
    return () => controller.abort()
  }, [schemeId, setId, status, tab, page, filters])

  async function run() {
    if (!schemeId || !setId || !scheme?.has_output || scheme.output_is_stale || busy) return
    setBusy(true); setError('')
    try {
      await request(`/api/classify/schemes/${schemeId}/run${setQuery}`, 'POST')
      setPage(1); setRevision(value => value + 1)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  function changeScheme(id: number) {
    const next = schemes.find(item => item.id === id)
    if (!sets.some(item => item.id === setId && item.is_grid_measure)) setSetId(sets.find(item => item.id === next?.initial_set_id && item.is_grid_measure)?.id || 0)
    setSchemeId(id); setScheme(null); setStatus(null); setPreview(null); setSource(null); setRowDetails(null); setFilters({}); setPage(1); setColumns(null)
  }
  function filterBy(key: string, value: string) { setFilters({ ...filters, [key]: value }); setPage(1) }
  function clearFilters() { setFilters({ q: filters.q || '' }); setPage(1) }
  const activeFilters = Object.entries(filters).filter(([key, value]) => key !== 'q' && value).length
  const query = (filters.q || '').toLowerCase()
  const metrics = report?.metrics.filter(item =>
    (!query || [item.name, item.dso, item.expected || '', item.status].join(' ').toLowerCase().includes(query))
    && (['name', 'dso', 'status'] as const).every(key => !filters[key] || item[key] === filters[key])) || []
  const metricOptions = (key: 'name' | 'dso' | 'status') => [...new Set(report?.metrics.map(item => item[key]).filter(Boolean))].sort()
  const unmappedFilters: Record<string, { key: string; options?: string[] }> = { field: { key: 'field', options: preview?.options.field }, value: { key: 'value' }, dso_slugs: { key: 'dso', options: preview?.options.dso } }
  const optionColumns: Record<string, string> = { record_type: 'inferred_record_type', asset_type: 'inferred_asset_type', measure_type: 'inferred_measure_type', flag: 'inferred_flags' }
  const defaults = ['row_id', 'inferred_record_type', 'inferred_measure_type', 'inferred_asset_type', 'inferred_grid_level', 'inferred_voltage', 'inferred_location_start', 'inferred_location_end', 'inferred_quality_classification', 'inferred_quality_location', 'inferred_flags']
  const nameTitle = scheme?.fields.find(field => field.key === 'measure_name')?.title || 'measure_name'
  const derived = new Set(preview?.derived || [])
  const visible = preview?.header.map((name, index) => ({ name, index })).filter(({ name }) =>
    tab === 'unmapped' || (columns ? columns.includes(name) : defaults.includes(name) || name === nameTitle)) || []

  return <div className="harmonize-page classify-page">
    <AppHeader page="classify" schemeId={schemeId} setId={setId} />
    <main className="harmonize-result-main">
      <header className="classify-heading">
        <div className="classify-heading-title"><h1>{t("Classification")}</h1><p>{report ? `${report.rows.toLocaleString()} · ${report.nap_round}` : 'NAP Tool'}</p></div>
        <div className="classify-actions">
          <label className="classify-selection"><span>{t("Harmonization schemes")}</span><select aria-label={t("Harmonization schemes")} value={schemeId} disabled={busy} onChange={event => changeScheme(Number(event.target.value))}>
            {schemes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label className="classify-selection"><span>{t("Set")}</span><select aria-label={t("Result set")} value={setId || ''} disabled={busy || setsLoading} onChange={event => { setSetId(Number(event.target.value)); setScheme(null); setStatus(null); setPreview(null); setSource(null); setRowDetails(null); setFilters({}); setPage(1); setColumns(null) }}>
            <option value="">{t("Select a set")}</option>{sets.filter(item => item.is_grid_measure).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <button className="classify-primary" type="button" disabled={busy || !setId || !scheme || !scheme.has_output || scheme.output_is_stale} onClick={() => void run()}><RotateCw size={14} />{busy ? t("Classifying…") : status?.has_output ? t("Rerun classification") : t("Run classification")}</button>
          {status?.has_output && <details className="classify-menu"><summary><Download size={14} />{t("Download")}<ChevronDown size={12} /></summary><div className="classify-menu-panel">
            {['classified.csv', 'validation_report.md', 'validation_report.json', 'unmapped_values.csv'].map(file => <a key={file} href={`/api/classify/schemes/${schemeId}/download/${file}${setQuery}`} download><Download size={13} />{file}</a>)}
          </div></details>}
          <a className="classify-back" href={resultUrl}><ArrowLeft size={14} />{t("Back to harmonized table")}</a>
        </div>
      </header>
      {setsError && <p role="alert">{t(setsError)}</p>}
      {error && <p className="harmonize-feedback error" role="alert">{t(error)}</p>}
      {status?.stale && <p className="classify-warning" role="status">{t("Classification results are stale: ")}{status.reason}</p>}
      {scheme && (!scheme.has_output || scheme.output_is_stale) && <p>{t("Generate the latest harmonized table first.")}</p>}
      {report && <div className="classify-summary">
        <button type="button" className={`classify-validation classify-${report.status}`} onClick={() => setTab('report')}>{t("Validation: ")}{report.status}</button>
        <span>{t("measure ")}<b>{report.record_types.measure?.toLocaleString() || 0}</b></span><span>{t("collective ")}<b>{report.record_types.collective?.toLocaleString() || 0}</b></span><span>{t("overview ")}<b>{report.record_types.overview?.toLocaleString() || 0}</b></span>
        <div className="classify-coverage">{[['inferred_asset_type', t("Asset type")], ['inferred_grid_level', t("Grid level")], ['inferred_measure_type', t("Measure type")]].map(([key, label]) => <span key={key}>{label} <b>{key in report.coverage ? `${(report.coverage[key] * 100).toFixed(1)}${t("%")}` : '—'}</b></span>)}</div>
      </div>}
      <div className="classify-workbar">
        <nav className="classify-tabs" aria-label={t("Classification views")}>{[['data', t("Classified data")], ['report', t("Validation report")], ['unmapped', t("Unmapped values")]].map(([key, title]) => <button key={key} type="button" aria-pressed={tab === key} onClick={() => { setTab(key); setPage(1); setFilters({}); setRowDetails(null) }}>{title}</button>)}</nav>
        {status?.has_output && <div className="classify-tools">
          <label className="classify-search"><Search size={14} /><input aria-label={t("Search classification results")} placeholder={t("Search results")} value={filters.q || ''} onChange={event => filterBy('q', event.target.value)} /></label>
          {tab === 'data' && <button type="button" aria-expanded={filtersOpen} onClick={() => setFiltersOpen(value => !value)}><ListFilter size={14} />{t("Filter")}{activeFilters > 0 && <span className="classify-filter-count">{activeFilters}</span>}</button>}
          {tab !== 'data' && activeFilters > 0 && <button type="button" onClick={clearFilters}><X size={14} />{t("Clear filters")}</button>}
          {tab === 'data' && preview && <details className="classify-menu classify-column-menu"><summary><SlidersHorizontal size={14} />{t("Choose columns")}<ChevronDown size={12} /></summary><div className="classify-menu-panel classify-columns">
            {[...preview.header].sort((first, second) => first.localeCompare(second, undefined, { numeric: true, sensitivity: 'base' })).map(name => <label key={name} title={name}><input type="checkbox" checked={visible.some(item => item.name === name)} onChange={event => { const current = visible.map(item => item.name); setColumns(event.target.checked ? [...current, name] : current.filter(item => item !== name)) }} /><span>{name}{derived.has(name) && <span className="derived-badge">ƒ</span>}</span></label>)}
          </div></details>}
        </div>}
      </div>
      {!status?.has_output && <p>{!setId ? t("Select a set") : status ? t("No classification results yet.") : t("Loading…")}</p>}
      {tab === 'report' && report && <>
        {status?.stale && report.expected_values_source === 'current_configuration' && <p>{t("This older report uses the current configuration for expected values.")}</p>}
        <p className="classify-report-count">{t("{0} of {1} metrics", metrics.length, report.metrics.length)}</p>
        <table className="classify-report">
          <thead><tr>
            <HeaderFilter label={t("Metric")} value={filters.name || ''} options={metricOptions('name')} onChange={value => filterBy('name', value)} />
            <HeaderFilter label={t("DSO")} value={filters.dso || ''} options={metricOptions('dso')} onChange={value => filterBy('dso', value)} />
            <th>{t("Value")}</th><th>{t("Empty share")}</th><th>{t("Expected value (pass criteria)")}</th>
            <HeaderFilter label={t("Status")} value={filters.status || ''} options={metricOptions('status')} onChange={value => filterBy('status', value)} />
          </tr></thead>
          <tbody>{metrics.map(item => <tr key={`${item.name}:${item.dso}`}>
            <td>{item.name}</td><td>{item.dso}</td><td>{item.value === null ? '-' : item.value.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
            <td>{item.empty_share == null ? '—' : `${(item.empty_share * 100).toFixed(1)}${t("%")} (${item.empty_count}/${item.row_count})`}</td>
            <td>{item.expected || t("Not recorded")}</td><td className={`classify-${item.status}`}>{item.status}</td>
          </tr>)}{metrics.length === 0 && <tr><td colSpan={6}>{t("No matching metrics.")}</td></tr>}</tbody>
        </table>
        {Object.entries(report).filter(([key]) => !['metrics', 'status', 'rows'].includes(key)).map(([key, value]) => <details key={key}><summary>{key}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>)}
      </>}
      {tab !== 'report' && status?.has_output && <>
        {tab === 'data' && filtersOpen && <div className="classify-filters">
          {[['dso', t("DSO")], ['record_type', t("Record type")], ['asset_type', t("Asset type")], ['measure_type', t("Measure type")], ['flag', t("Flags")]].map(([key, label]) => <label key={key}><span>{label}</span><select value={filters[key] || ''} onChange={event => filterBy(key, event.target.value)}><option value="">{t("All ")}</option>{(preview?.options[optionColumns[key] || key] || []).map(value => <option key={value} value={value}>{value}</option>)}</select></label>)}
          <button type="button" onClick={clearFilters}>{t("Clear filters")}</button>
        </div>}
        {preview ? <>
          <div className="harmonize-result-table-wrap"><table className="harmonize-result-table"><thead><tr>{tab === 'data' && <th>{t("Details")}</th>}{visible.map(({ name }) => tab === 'unmapped' && unmappedFilters[name]
            ? <HeaderFilter key={name} label={name} value={filters[unmappedFilters[name].key] || ''} options={unmappedFilters[name].options} onChange={value => filterBy(unmappedFilters[name].key, value)} />
            : <th key={name}>{name}{derived.has(name) && <span className="derived-badge" title={t("Derived column")}>ƒ</span>}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}>{tab === 'data' && <td><button type="button" onClick={() => setRowDetails(row)}>{t("View")}</button></td>}{visible.map(({ name, index: column }) => <td key={name} title={name === 'source_cells_json' ? '' : row[column]}>{name === 'source_cells_json' ? <button type="button" onClick={() => setSource(row[column])}>{t("View source")}</button> : row[column]}</td>)}</tr>)}</tbody></table></div>
          <div className="harmonize-result-pager"><span>{preview.total_rows} {t("  rows ·  ")}{page} {t("  page")}</span><button type="button" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>{t("Previous page")}</button><button type="button" disabled={page * preview.page_size >= preview.total_rows} onClick={() => setPage(value => value + 1)}>{t("Next page")}</button></div>
        </> : <p>{t("Loading results…")}</p>}
      </>}
      {rowDetails && preview && <RowDetails headers={preview.header} derived={derived} row={rowDetails} onClose={() => setRowDetails(null)} onSource={setSource} />}

    </main>
    {source !== null && <SourceDialog value={source} onClose={() => setSource(null)} />}
  </div>
}

/** Column header with a select for known options, otherwise a contains-search field. */
function HeaderFilter({ label, value, options, onChange }: { label: string; value: string; options?: string[]; onChange: (value: string) => void }) {
  return <th className="classify-header-filter"><span>{label}</span>{options
    ? <select aria-label={t("Filter by {0}", label)} value={value} onChange={event => onChange(event.target.value)}><option value="">{t("All ")}</option>{options.map(option => <option key={option} value={option}>{option}</option>)}</select>
    : <input type="search" aria-label={t("Filter by {0}", label)} placeholder={t("Search")} value={value} onChange={event => onChange(event.target.value)} />}</th>
}

function RowDetails({ headers, derived, row, onClose, onSource }: { headers: string[]; derived: Set<string>; row: string[]; onClose: () => void; onSource: (value: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} className="harmonize-source-dialog classify-detail-dialog" onClose={onClose} aria-label={t("Row details")}>
    <header><h2>{t("Row details")}</h2><button type="button" aria-label={t("Close details")} onClick={() => dialog.current?.close()}><X size={16} /></button></header>
    <dl>{headers.map((name, index) => <div key={name}><dt>{name}{derived.has(name) && <span className="derived-badge" title={t("Derived column")}>ƒ</span>}</dt><dd>{name === 'source_cells_json' ? <button type="button" onClick={() => onSource(row[index])}>{t("View source cells")}</button> : row[index] || t("(empty)")}</dd></div>)}</dl>
  </dialog>
}
