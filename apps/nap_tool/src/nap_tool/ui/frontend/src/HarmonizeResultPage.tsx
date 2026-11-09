// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, FilePlus2, X } from 'lucide-react'
import { AppHeader } from './AppHeader'
import { locale, t } from './i18n'
import { setsApi, useHarmonizeSets } from './harmonizeSets'

type Scheme = {
  id: number
  name: string
  initial_set_id: number | null
  has_output: boolean
  output_is_stale: boolean
  generated_at: string | null
  fields: { key: string }[]
}

type Preview = {
  header: string[]
  rows: string[][]
  total_rows: number
  page: number
  page_size: number
}

type RowProvenance = {
  schema_version: number
  origin: { document_title: string | null; document_id: number; extract_table_id: number; row_number: number; extract_is_confirmed: boolean; clean_is_confirmed: boolean }
  sources: { stage: string; clean_table_id: number | null; file_path: string | null; file_hash: string; row_number: number; row_exists: boolean; header_row: number; headers: string[]; cells: string[]; review_path: string; bindings: { field: string; column_number: number }[] }[]
}

export function SourceDialog({ value, onClose }: { value: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  let data: RowProvenance | null = null
  let formattedValue = value
  try {
    const parsed = JSON.parse(value) as RowProvenance
    formattedValue = JSON.stringify(parsed, null, 2)
    if (parsed?.origin && Array.isArray(parsed.sources)) data = parsed
  } catch { /* Older results can still be inspected as text. */ }
  const stageNames: Record<string, string> = { clean_review: t("Reviewed cleaned table"), clean_table: t("Automatic cleaned table"), extract_reviewed: t("reviewed extracted table"), extract_table: t("Original extracted table") }
  return <dialog ref={dialog} className="harmonize-source-dialog" aria-labelledby="source-dialog-title" onClose={onClose}>
    <button className="harmonize-dialog-close" type="button" aria-label={t("Close source details")} onClick={() => dialog.current?.close()}><X size={18} /></button>
    <h2 id="source-dialog-title">{t("Row provenance")}</h2>
    {data ? <>
      <p>{data.origin.document_title || t("Document #{0}", data.origin.document_id)} {t(" · Extracted table #")}{data.origin.extract_table_id} {t(" · CSV  ")}{data.origin.row_number} {t("  rows")}</p>
      <p>{t("Extraction")}{data.origin.extract_is_confirmed ? t("Reviewed") : t("Pending review")} {t(" · Cleaning")}{data.origin.clean_is_confirmed ? t("Reviewed") : t("Pending review")}</p>
      {data.sources.map((source, index) => <section className="harmonize-source-version" key={index}>
        <div className="harmonize-source-heading"><strong>{stageNames[source.stage] || source.stage}{source.clean_table_id ? ` #${source.clean_table_id}` : ''}</strong>
          {source.review_path.startsWith('/ui/overview?') && <a href={source.review_path} target="_blank" rel="noreferrer">{t("Open review page")}</a>}
        </div>
        <details><summary>{t("Version and file details")}</summary><p>{t("CSV file: ")}<code>{source.file_path || t("Not recorded")}</code></p><p>{t("SHA-256: ")}<code>{source.file_hash}</code></p><p>{t("Header:  ")}{source.header_row} {t("  rows; Data:  ")}{source.row_number} {t("  rows")}</p></details>
        {source.row_exists ? <table className="harmonize-source-cells"><thead><tr><th>{t("Column number")}</th><th>{t("Source column name")}</th><th>{t("Cell in this row")}</th><th>{t("Mapped field")}</th></tr></thead><tbody>
          {source.cells.map((cell, column) => <tr key={column}><td>{column + 1}</td><td>{source.headers[column] || t("(no column name)")}</td><td>{cell || t("(empty)")}</td><td>{source.bindings.filter((binding) => binding.column_number === column + 1).map((binding) => binding.field).join(', ')}</td></tr>)}
        </tbody></table> : <p>{t("This version has no such row.")}</p>}
      </section>)}
      <details className="harmonize-source-json"><summary>{t("View formatted JSON")}</summary><pre>{formattedValue}</pre></details>
    </> : <pre>{formattedValue}</pre>}
  </dialog>
}

async function request<T>(path: string, method = 'GET'): Promise<T> {
  const response = await fetch(path, { method })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || t("Request failed({0})", response.status))
  }
  return response.json() as Promise<T>
}

function schemeFromUrl(): number | null {
  const value = Number(new URLSearchParams(location.search).get('scheme'))
  return Number.isInteger(value) && value > 0 ? value : null
}

function setFromUrl(): number | null {
  const value = Number(new URLSearchParams(location.search).get('set'))
  return Number.isInteger(value) && value > 0 ? value : null
}

function resultPath(schemeId: number | null, setId: number | null): string {
  const query = new URLSearchParams()
  if (schemeId) query.set('scheme', String(schemeId))
  if (setId) query.set('set', String(setId))
  return `/ui/harmonize/result${query.size ? `?${query}` : ''}`
}

export function HarmonizeResultPage() {
  const { sets, loading: setsLoading, error: setsError, reload: reloadSets } = useHarmonizeSets()
  const [setId, setSetId] = useState<number | null>(setFromUrl)
  const [schemes, setSchemes] = useState<Scheme[]>([])
  const [schemesLoaded, setSchemesLoaded] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const [schemeId, setSchemeId] = useState<number | null>(schemeFromUrl)
  const [scheme, setScheme] = useState<Scheme | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [sourceValue, setSourceValue] = useState<string | null>(null)

  useEffect(() => { document.title = t("NAP Tool · Harmonized results") }, [])

  useEffect(() => {
    request<Scheme[]>('/api/harmonize/schemes').then((items) => {
      setSchemes(items)
      setSchemesLoaded(true)
    }).catch((reason: Error) => setError(reason.message))
    const onPop = () => { setSchemeId(schemeFromUrl()); setSetId(setFromUrl()); setPage(1) }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    if (initialized || setsLoading || !schemesLoaded) return
    const explicitScheme = schemes.find(item => item.id === schemeFromUrl())
    const initialSet = sets.find(item => item.id === setFromUrl())
      ?? sets.find(item => item.id === explicitScheme?.initial_set_id) ?? sets[0]
    const compatible = schemes
    const initialScheme = compatible.find(item => item.id === explicitScheme?.id)
      ?? compatible.find(item => item.id === initialSet?.current_scheme_id) ?? compatible[0]
    setSetId(initialSet?.id ?? null); setSchemeId(initialScheme?.id ?? null)
    setInitialized(true)
    history.replaceState(null, '', resultPath(initialScheme?.id ?? null, initialSet?.id ?? null))
  }, [initialized, setsLoading, schemesLoaded, schemes, sets])

  useEffect(() => {
    setScheme(null); setPreview(null); setSourceValue(null); setError('')
    if (!initialized || !schemeId) return
    let cancelled = false
    request<Scheme>(`/api/harmonize/schemes/${schemeId}${setId ? `?set_id=${setId}` : ''}`)
      .then((item) => { if (!cancelled) setScheme(item) })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [initialized, schemeId, setId])

  useEffect(() => {
    setPreview(null)
    if (!schemeId || !setId || !scheme?.has_output) return
    let cancelled = false
    request<Preview>(`/api/harmonize/schemes/${schemeId}/preview?set_id=${setId}&page=${page}&page_size=100`)
      .then((item) => { if (!cancelled) setPreview(item) })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [schemeId, setId, scheme?.has_output, scheme?.output_is_stale, scheme?.generated_at, page])

  const selectedSet = sets.find((item) => item.id === setId)
  const compatibleSchemes = schemes

  useEffect(() => {
    if (!initialized || setsLoading || !selectedSet || !schemes.length || busy) return
    const compatible = schemes
    if (!compatible.some((item) => item.id === schemeId)) {
      const nextId = compatible.find(item => item.id === selectedSet.current_scheme_id)?.id ?? compatible[0]?.id ?? null
      setSchemeId(nextId); setScheme(null); setPreview(null); setPage(1)
      history.replaceState(null, '', resultPath(nextId, setId))
    }
  }, [initialized, setsLoading, selectedSet, schemes, schemeId, setId, busy])

  function chooseScheme(id: number) {
    const selected = schemes.find((item) => item.id === id)
    const nextSet = setId ?? selected?.initial_set_id ?? null
    setSchemeId(id); setSetId(nextSet); setScheme(null); setPreview(null); setPage(1); setNotice('')
    history.pushState(null, '', resultPath(id, nextSet))
  }

  function chooseSet(id: number | null) {
    const selected = sets.find((item) => item.id === id)
    const compatible = schemes
    const nextScheme = compatible.find(item => item.id === selected?.current_scheme_id)?.id ?? compatible.find((item) => item.id === schemeId)?.id ?? compatible[0]?.id ?? null
    setSetId(id); setSchemeId(nextScheme); setScheme(null); setPreview(null); setPage(1); setNotice('')
    history.pushState(null, '', resultPath(nextScheme, id))
  }

  async function setDefaultScheme() {
    if (!selectedSet || !schemeId || busy) return
    setBusy(true); setError('')
    try {
      await setsApi(`/${selectedSet.id}/current-scheme`, 'PUT', {
        current_scheme_id: schemeId, expected_current_scheme_id: selectedSet.current_scheme_id,
      })
      reloadSets(); setNotice(t("Set default scheme saved"))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  async function generate() {
    if (!schemeId || !setId || busy) return
    setBusy(true); setError(''); setNotice(''); setPreview(null)
    try {
      const result = await request<{ tables: number; rows: number; conflicts: number }>(
        `/api/harmonize/schemes/${schemeId}/generate?set_id=${setId}`, 'POST',
      )
      const updated = await request<Scheme>(`/api/harmonize/schemes/${schemeId}?set_id=${setId}`)
      setScheme(updated); setPage(1)
      setNotice(t("Generated {0} tables and {1} rows; {2} multivalued cells kept as JSON arrays", result.tables, result.rows, result.conflicts))
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Generation failed")) }
    finally { setBusy(false) }
  }

  const sourceIndex = preview?.header.indexOf('source_cells_json') ?? -1
  const visibleColumns = preview?.header.map((header, index) => ({ header, index })).filter((column) => column.index !== sourceIndex) ?? []
  if (sourceIndex >= 0) visibleColumns.splice(Math.min(1, visibleColumns.length), 0, { header: t("Source details"), index: sourceIndex })

  return <div className="harmonize-page harmonize-result-page">
    <AppHeader page="result" schemeId={schemeId} setId={setId} />
    {(error || setsError || notice) && <div className={`harmonize-feedback ${error ? 'error' : ''}`} role="status">{t(error || setsError || notice)}</div>}
    <main className="harmonize-result-main">
      <div className="harmonize-result-controls">
        <label>{t("Set")}<select aria-label={t("Result set")} value={setId ?? ''} disabled={busy || setsLoading} onChange={(event) => chooseSet(event.target.value ? Number(event.target.value) : null)}>
          <option value="">{t("Select a set")}</option>{sets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label>{t("Select scheme")}<select aria-label={t("Select harmonization scheme")} value={schemeId ?? ''} disabled={busy} onChange={(event) => chooseScheme(Number(event.target.value))}>{compatibleSchemes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <button type="button" disabled={busy || setsLoading || !selectedSet || !scheme || selectedSet.current_scheme_id === schemeId} onClick={() => void setDefaultScheme()}>{selectedSet && selectedSet.current_scheme_id === schemeId ? t("Set default scheme") : t("Set as default")}</button>
        <div className="harmonize-result-status"><span className={scheme?.output_is_stale ? 'stale' : ''}>{setId && scheme?.has_output ? scheme.output_is_stale ? t("Source or scheme changed; regenerate results") : t("Generated  {0}", new Date(scheme.generated_at!).toLocaleString(locale === 'de' ? 'de-DE' : 'en-US')) : t("No results generated yet")}</span></div>
        <button className="harmonize-primary" type="button" onClick={generate} disabled={!scheme || !selectedSet || busy || !scheme.fields.length}><FilePlus2 size={15} /> {busy ? t("Generating…") : t("Generate harmonized table")}</button>
        {setId && scheme?.has_output && <a className="harmonize-download" href={`/api/harmonize/schemes/${scheme.id}/download?set_id=${setId}`}><Download size={15} /> {t(" Download CSV")}</a>}
      </div>
      {preview ? <>
        <div className="harmonize-result-table-wrap"><table className="harmonize-result-table"><thead><tr>{visibleColumns.map(({ header, index }) => <th key={index} title={header}>{header}</th>)}</tr></thead><tbody>{preview.rows.map((row, rowIndex) => <tr key={rowIndex}>{visibleColumns.map(({ index }) => <td key={index} title={index === sourceIndex ? '' : row[index] || ''}>{index === sourceIndex ? <button className="harmonize-source-button" type="button" onClick={() => setSourceValue(row[index])}>{t("View source")}</button> : row[index] || ''}</td>)}</tr>)}</tbody></table></div>
        <div className="harmonize-result-pager"><span>{locale === 'de' ? 'Insgesamt' : t("Total")} {preview.total_rows.toLocaleString(locale === 'de' ? 'de-DE' : 'en-US')} {locale === 'de' ? 'Zeilen' : 'rows'} · {locale === 'de' ? 'Seite' : t("Page")} {page} / {Math.max(1, Math.ceil(preview.total_rows / preview.page_size))}</span><button type="button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}><ChevronLeft size={14} /> {t(" Previous page")}</button><button type="button" disabled={page * preview.page_size >= preview.total_rows} onClick={() => setPage((current) => current + 1)}>{t("Next page ")}<ChevronRight size={14} /></button></div>
      </> : <div className="harmonize-result-empty">{!setId ? t("Select a set and scheme to generate a result.") : scheme?.output_is_stale ? t("Source or scheme changed; regenerate the harmonized table.") : scheme?.has_output ? t("Loading results…") : t("Select a scheme and generate a harmonized table. Results will appear here.")}</div>}
    </main>
    {sourceValue !== null && <SourceDialog value={sourceValue} onClose={() => setSourceValue(null)} />}
  </div>
}
