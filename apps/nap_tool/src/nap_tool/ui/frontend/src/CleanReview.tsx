// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useState, type FocusEvent } from 'react'
import { CleanFilters, type CleanFilter } from './CleanFilters'
import { ArrowLeft, Check, CircleCheck, Plus, RotateCcw, Save, Settings2, Trash2, X } from 'lucide-react'
import { locale, t } from './i18n'

type ColumnRule = {
  index: number
  kind: 'text' | 'money' | 'number' | 'date' | 'choice'
  configured?: boolean
  source_unit: string
  target_unit: string
  choices: Record<string, string[]>
}

type CleanConfig = {
  header_row: number
  decimal_separator: ',' | '.'
  thousands_separator: '.' | ',' | '' | ' '
  columns: ColumnRule[]
  deleted_rows?: number[]
}

type CellStatus = { row: number; column: number; original: string; status: string; note: string }
type ChoiceEntry = { standard: string; aliases: string }

type Review = {
  id: number
  title: string
  source_rows: string[][]
  automatic_rows: string[][]
  reviewed_rows: string[][] | null
  rows: string[][]
  kept_rows: number[]
  cells: CellStatus[]
  config: CleanConfig
  source_hash: string
  clean_hash: string
  reviewed_hash: string | null
  is_stale: boolean
  review_is_stale: boolean
  is_confirmed: boolean
  note: string
}

type Props = { cleanId: number; onClose: () => void; onSaved: () => void; filters: CleanFilter[]; onFiltersChange: (value: CleanFilter[]) => void }

function sameGrid(first: string[][], second: string[][]): boolean {
  return JSON.stringify(first) === JSON.stringify(second)
}

async function request(path: string, method = 'GET', body?: object): Promise<unknown> {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const result = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(result.detail || t("Operation failed({0})", response.status))
  }
  return response.json()
}

export function CleanReview({ cleanId, onClose, onSaved, filters, onFiltersChange }: Props) {
  const [review, setReview] = useState<Review | null>(null)
  const [rows, setRows] = useState<string[][]>([])
  const [view, setView] = useState<'source' | 'automatic' | 'reviewed'>('reviewed')
  const [column, setColumn] = useState<number | null>(null)
  const [draft, setDraft] = useState<ColumnRule | null>(null)
  const [decimal, setDecimal] = useState<',' | '.'>(',')
  const [thousands, setThousands] = useState<'.' | ',' | '' | ' '>('.')
  const [choiceEntries, setChoiceEntries] = useState<ChoiceEntry[]>([])
  const [headerRowDraft, setHeaderRowDraft] = useState(1)
  const [noteOpen, setNoteOpen] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    setReview(null)
    setError('')
    request(`/api/clean-review/${cleanId}`).then((data) => {
      if (!active) return
      const loaded = data as Review
      setReview(loaded)
      setRows(loaded.rows.map((row) => [...row]))
      setNote(loaded.note)
      setDecimal(loaded.config.decimal_separator)
      setThousands(loaded.config.thousands_separator)
      setHeaderRowDraft(loaded.config.header_row || 1)
      setColumn(null)
    }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [cleanId])

  const dirty = review !== null && !sameGrid(rows, review.rows)
  const headerRow = review?.config.header_row || 1
  const headerIndex = headerRow - 1
  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault() }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])

  const statuses = useMemo(() => {
    const result = new Map<string, CellStatus>()
    for (const cell of review?.cells || []) result.set(`${cell.row}:${cell.column}`, cell)
    return result
  }, [review?.cells])
  const unresolved = review?.cells.filter((cell) => cell.status === 'unresolved').length || 0
  const columnUnresolved = useMemo(() => {
    const result = new Set<number>()
    for (const cell of review?.cells || []) if (cell.status === 'unresolved') result.add(cell.column)
    return result
  }, [review?.cells])
  const configuredColumns = useMemo(() => new Set(
    review?.config.columns.filter((rule) => rule.configured || rule.kind !== 'text').map((rule) => rule.index) || [],
  ), [review?.config.columns])
  const diffs = useMemo(() => {
    if (!review) return 0
    return rows.reduce((sum, row, rowIndex) => sum + (rowIndex < headerIndex ? 0 : row.filter((value, columnIndex) =>
      value !== (review.automatic_rows[rowIndex]?.[columnIndex] ?? ''),
    ).length), 0)
  }, [rows, review, headerIndex])

  const matches = useMemo(() => {
    const matchedRows = new Set<number>()
    const matchedColumns = new Set<number>()
    const matchedCells = new Set<string>()
    let unresolvedModified = 0
    if (review) for (const [position, row] of rows.entries()) {
      if (position < headerIndex) continue
      const rowIndex = review.kept_rows[position] ?? position
      for (const [columnIndex, value] of row.entries()) {
      const key = `${rowIndex}:${columnIndex}`
      const rowPosition = position
      const changed = value !== (review.automatic_rows[rowPosition]?.[columnIndex] ?? '')
      const failed = statuses.get(key)?.status === 'unresolved'
      if (failed && changed) unresolvedModified++
      if (filters.some((filter) => filter === 'manual' ? changed : filter === 'unresolved_modified' ? failed && changed : failed && !changed)) {
        matchedRows.add(rowIndex); matchedColumns.add(columnIndex); matchedCells.add(key)
      }
      }
    }
    return { rows: matchedRows, columns: matchedColumns, cells: matchedCells, unresolvedModified }
  }, [review, rows, statuses, filters.join(','), headerIndex])

  function editCell(rowIndex: number, columnIndex: number, value: string) {
    setRows((current) => current.map((row, index) => index === rowIndex
      ? row.map((cell, cellIndex) => cellIndex === columnIndex ? value : cell) : row))
  }

  function openColumn(index: number) {
    if (!review) return
    const rule = review.config.columns.find((item) => item.index === index) || {
      index, kind: 'text' as const, source_unit: '', target_unit: '', choices: {},
    }
    setColumn(index)
    setDraft({ ...rule, choices: { ...rule.choices } })
    const entries = Object.entries(rule.choices).map(([standard, aliases]) => ({
      standard, aliases: aliases.join('\n'),
    }))
    setChoiceEntries(entries.length ? entries : [{ standard: '', aliases: '' }])
  }

  async function updateConfig(config: CleanConfig, success: string) {
    if (!review || busy) return false
    if (dirty && !window.confirm(t("Cell edits are unsaved. Applying a rule reloads the table. Continue?"))) return false
    setBusy(true); setError(''); setNotice('')
    try {
      await request(`/api/clean-review/${cleanId}/rules`, 'PUT', {
        config, expected_clean_hash: review.clean_hash, expected_source_hash: review.source_hash,
      })
      const updated = await request(`/api/clean-review/${cleanId}`) as Review
      setReview(updated); setRows(updated.rows.map((row) => [...row]))
      setHeaderRowDraft(updated.config.header_row || 1)
      if (column !== null) setDraft(updated.config.columns.find((item) => item.index === column) || null)
      setNotice(success)
      onSaved()
      return true
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Rule update failed")); return false }
    finally { setBusy(false) }
  }

  function choiceMapping(): Record<string, string[]> | null {
    const mapping: Record<string, string[]> = {}
    const used = new Set<string>()
    for (const entry of choiceEntries) {
      const standard = entry.standard.trim()
      const aliases = entry.aliases.split('\n').map((item) => item.trim()).filter(Boolean)
      if (!standard && aliases.length) { setError(t("Enter a normalized value for this mapping group first")); return null }
      if (standard) {
        for (const value of [standard, ...aliases]) {
          const key = value.toLocaleLowerCase()
          if (used.has(key)) { setError(t("“{0}” appears more than once in the mapping; keep only one entry", value)); return null }
          used.add(key)
        }
        mapping[standard] = aliases
      }
    }
    if (!Object.keys(mapping).length) { setError(t("Add at least one normalized value")); return null }
    return mapping
  }

  async function applyRule(nextRule = draft, nextDecimal = decimal, nextThousands = thousands) {
    if (!review || !nextRule) return
    const savedRule = { ...nextRule, configured: true }
    await updateConfig({
      header_row: review.config.header_row || 1,
      decimal_separator: nextDecimal,
      thousands_separator: nextThousands,
      columns: [...review.config.columns.filter((item) => item.index !== nextRule.index), savedRule]
        .sort((a, b) => a.index - b.index),
      deleted_rows: review.config.deleted_rows ?? [],
    }, t("Rule applied; automatic cleaning updated"))
  }

  async function deleteRule() {
    if (!review || column === null) return
    const deleted = await updateConfig({
      ...review.config,
      columns: review.config.columns.filter((item) => item.index !== column),
    }, t("Rule deleted; column is unconfigured again"))
    if (deleted) setColumn(null)
  }

  async function applyHeaderRow() {
    if (!review || headerRowDraft === (review.config.header_row || 1)) return
    const deleted_rows = (review.config.deleted_rows ?? []).filter((row) => row >= headerRowDraft)
    await updateConfig({ ...review.config, header_row: headerRowDraft, deleted_rows }, t("Row {0} set as the header; automatic cleaning updated", headerRowDraft))
  }

  function applyOnBlur(event: FocusEvent<HTMLInputElement | HTMLTextAreaElement>, nextRule: ColumnRule) {
    if (event.relatedTarget instanceof HTMLElement && event.relatedTarget.classList.contains('clean-apply-button')) return
    void applyRule(nextRule)
  }

  async function save(confirm: boolean) {
    if (!review || busy) return
    if (confirm && unresolved > 0 && !window.confirm(t("Automatic cleaning still has  {0}  unresolved cells. Confirm you have checked them before continuing?", unresolved))) return
    setBusy(true); setError(''); setNotice('')
    try {
      await request(`/api/clean-review/${cleanId}`, 'PUT', {
        rows, expected_clean_hash: review.clean_hash,
        expected_reviewed_hash: review.reviewed_hash, confirm,
      })
      const updated = await request(`/api/clean-review/${cleanId}`) as Review
      setReview(updated); setRows(updated.rows.map((row) => [...row]))
      setNotice(confirm ? t("Manual review confirmed") : t("Draft saved"))
      onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Save failed")) }
    finally { setBusy(false) }
  }

  async function saveNote() {
    if (!review || busy) return
    setBusy(true); setError('')
    try {
      await request(`/api/clean-review/${cleanId}/metadata`, 'PATCH', { note })
      setReview({ ...review, note }); setNoteOpen(false); setNotice(t("Note saved"))
      onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Failed to save note")) }
    finally { setBusy(false) }
  }

  const deletedRows = new Set(review?.config.deleted_rows ?? [])

  async function setRowDeleted(rowIndex: number, deleted: boolean) {
    if (!review) return
    const next = new Set(deletedRows)
    if (deleted) next.add(rowIndex); else next.delete(rowIndex)
    await updateConfig({ ...review.config, deleted_rows: [...next].sort((a, b) => a - b) },
      deleted ? t("Row {0} deleted; automatic cleaning updated", rowIndex + 1) : t("Row {0} restored; automatic cleaning updated", rowIndex + 1))
  }

  function close() {
    if (dirty && !window.confirm(t("Cell changes are unsaved. Return anyway?"))) return
    onClose()
  }

  if (!review) return <section className="clean-review-workspace"><div className="review-message">
    <span>{error || t("Loading cleaned table…")}</span><button className="review-close" type="button" onClick={close}><ArrowLeft size={14} /> {t(" Back to overview")}</button>
  </div></section>

  const visibleRows = view === 'source' ? review.source_rows : view === 'automatic' ? review.automatic_rows : rows
  const columnCount = visibleRows.reduce((width, row) => Math.max(width, row.length), 0)
  const headerCells = Array.from({ length: columnCount }, (_, index) => visibleRows[headerIndex]?.[index] ?? '')
  const visibleColumns = headerCells.map((_, index) => index).filter((index) => !filters.length || matches.columns.has(index))
  const positionOf = new Map(review.kept_rows.map((source, position) => [source, position]))
  const visibleRowIndices = review.source_rows.map((_, index) => index).filter((index) => index > headerIndex
    && (view === 'source' || !deletedRows.has(index)) && (!filters.length || matches.rows.has(index)))
  const headerCandidate = review.source_rows[headerRowDraft - 1]
  const validHeaderCandidate = headerRowDraft >= 1 && headerRowDraft <= review.source_rows.length && Boolean(headerCandidate?.some((cell) => cell.trim()))
  const headerPreview = headerCandidate?.filter((cell) => cell.trim()).slice(0, 3).join(' · ') || t("This row is empty and cannot be a header")
  const choiceValues = column === null ? [] : [...new Set(review.source_rows.slice(headerRow)
    .map((row) => row[column]?.trim()).filter((value): value is string => Boolean(value)))]
  return <section className="clean-review-workspace" aria-label={t("Cleaned table review")}>
    <div className="clean-review-bar">
      <div className="clean-review-heading"><strong>{review.title}</strong><span>{t("Full table · ")}{Math.max(0, visibleRows.length - headerRow)} {t(" data rows · ")}{headerCells.length} {t("  columns")}</span></div>
      <div className="clean-review-tools">
        <div className="review-table-switch" role="group" aria-label={t("Cleaned table versions")}>
          <button type="button" aria-pressed={view === 'source'} onClick={() => setView('source')}>{t("Before cleaning")}</button>
          <button type="button" aria-pressed={view === 'automatic'} onClick={() => setView('automatic')}>{t("Automatic cleaning")}</button>
          <button type="button" aria-pressed={view === 'reviewed'} onClick={() => setView('reviewed')}>{t("Manual review")}{review.reviewed_hash ? '' : t(" · Unsaved")}</button>
        </div>
        <span className="clean-review-count">{unresolved - matches.unresolvedModified} {t(" Unresolved · ")}{matches.unresolvedModified} {t("  manual edits after unresolved values · ")}{diffs} {t("  manual differences")}</span>
        <button className="review-close" type="button" onClick={close}><ArrowLeft size={14} /> {t(" Back to overview")}</button>
      </div>
    </div>
    <div className="clean-review-actions">
      <button type="button" onClick={() => save(false)} disabled={busy || view !== 'reviewed' || (!dirty && review.reviewed_hash !== null)}><Save size={15} /> {t(" Save draft")}</button>
      <button className={review.is_confirmed && !dirty && !review.review_is_stale ? 'is-confirmed' : 'confirm'} type="button" onClick={() => save(true)} disabled={busy || view !== 'reviewed' || (review.is_confirmed && !dirty && !review.review_is_stale)}>
        {review.is_confirmed && !dirty && !review.review_is_stale ? <CircleCheck size={15} /> : <Check size={15} />}{review.is_confirmed && !dirty && !review.review_is_stale ? t("Confirmed") : t("Save and confirm")}
      </button>
      <button type="button" onClick={() => { setNote(review.note); setNoteOpen(!noteOpen) }}>{review.note ? <CircleCheck size={15} /> : <Settings2 size={15} />}{review.note ? t("Note saved") : t("Note")}</button>
      <div className="clean-header-row-controls">
        <label>{t("Column header row ")}<input type="number" min={1} max={review.source_rows.length} value={headerRowDraft} onChange={(event) => setHeaderRowDraft(Number(event.target.value))} aria-label={t("CSV row number containing column names")} /></label>
        <span className="clean-header-row-preview" title={headerPreview}>{locale === 'de' ? 'Vorschau Zeile' : t("Row preview")} {headerRowDraft || '—'}: {headerPreview}</span>
        <button type="button" onClick={() => void applyHeaderRow()} disabled={busy || !validHeaderCandidate || headerRowDraft === headerRow}>{t("Apply and recalculate")}</button>
        <small>{t("You can also click a row number on the left. Rows before the header are not treated as data.")}</small>
      </div>
      {review.review_is_stale && <span className="clean-review-warning">{t("Review again after rule changes")}</span>}
      {review.is_stale && <span className="clean-review-warning">{t("Extraction source changed; recalculate rules")}</span>}
    </div>
    {noteOpen && <div className="review-note-panel"><label htmlFor="clean-review-note">{t("Manual review notes")}</label><textarea id="clean-review-note" value={note} rows={2} maxLength={5000} onChange={(event) => setNote(event.target.value)} /><div><button type="button" onClick={() => setNoteOpen(false)}>{t("Cancel")}</button><button type="button" className="review-note-save" onClick={saveNote} disabled={busy}>{t("Save note")}</button></div></div>}
    {(error || notice) && <div className={`review-feedback ${error ? 'review-error' : ''}`} role="status">{t(error || notice)}</div>}
    <div className="clean-review-filter-bar"><CleanFilters value={filters[0] ?? null} onChange={(value) => onFiltersChange(value ? [value] : [])} label={t("Reviewed cells")} /><span>{filters.length ? t("Show {0} matching rows and {1} columns", visibleRowIndices.length, visibleColumns.length) : t("Show all rows and columns")}{dirty ? t(" · includes unsaved edits") : ''}</span></div>
    {filters.includes('manual') && matches.rows.has(headerIndex) && <div className="clean-header-changes">{t("Manual header edits: ")}{visibleColumns.filter((index) => matches.cells.has(`${headerIndex}:${index}`)).map((index) => <span key={index}>{t(" ")}{index + 1} {t("  columns: ")}{review.automatic_rows[headerIndex][index] || t("(empty)")} → {rows[headerIndex][index] || t("(empty)")}</span>)}</div>}
    {filters.length > 0 && !visibleColumns.length && <div className="clean-filter-empty">{t("No matching cells.")}</div>}
    <div className="clean-review-grid-wrap">
      <table className="clean-review-grid"><thead><tr><th className="clean-row-number" title={t("Column names from CSV row {0}", headerRow)}>#{headerRow}</th>{visibleColumns.map((index) =>
        <th key={index} className={view === 'source' ? 'is-untouched' : columnUnresolved.has(index) ? 'has-unresolved' : configuredColumns.has(index) ? 'is-configured' : 'is-untouched'}>
          <button type="button" onClick={() => openColumn(index)} title={configuredColumns.has(index) ? t("Cleaning rule set; click to edit") : t("Click to configure this column")}><span>{headerCells[index] || t(" {0}  columns", index + 1)}</span><span className="clean-rule-indicator"><Settings2 size={13} />{configuredColumns.has(index) && <small>{t("Configured")}</small>}</span></button>
        </th>)}</tr></thead><tbody>{visibleRowIndices.map((rowIndex) => {
          const position = view === 'source' ? rowIndex : positionOf.get(rowIndex) ?? rowIndex
          const isDeleted = deletedRows.has(rowIndex)
          return <tr key={rowIndex} className={isDeleted ? 'is-row-deleted' : undefined}>
          <th className="clean-row-number"><button className={headerRowDraft === rowIndex + 1 ? 'is-candidate' : undefined} type="button" onClick={() => setHeaderRowDraft(rowIndex + 1)} title={t("Use CSV row {0} as the header", rowIndex + 1)}>{rowIndex + 1}</button>
            <button className="clean-row-delete" type="button" disabled={busy} onClick={() => void setRowDeleted(rowIndex, !isDeleted)} title={isDeleted ? t("Restore row {0}", rowIndex + 1) : t("Delete row {0}", rowIndex + 1)} aria-label={isDeleted ? t("Restore row {0}", rowIndex + 1) : t("Delete row {0}", rowIndex + 1)}>{isDeleted ? <RotateCcw size={11} /> : <Trash2 size={11} />}</button></th>
          {visibleColumns.map((columnIndex) => {
            const value = visibleRows[position]?.[columnIndex] ?? ''
            const status = view === 'source' ? undefined : statuses.get(`${rowIndex}:${columnIndex}`)
            const changed = view !== 'source' && rows[position]?.[columnIndex] !== review.automatic_rows[position]?.[columnIndex]
            return <td key={columnIndex} className={`${status?.status === 'unresolved' ? 'is-unresolved' : configuredColumns.has(columnIndex) ? 'is-clean' : 'is-untouched'} ${changed ? 'is-human-diff' : ''} ${filters.length && matches.cells.has(`${rowIndex}:${columnIndex}`) ? 'is-filter-match' : ''}`} title={status ? t("Original: {0}{1}", status.original, status.note ? ` · ${status.note}` : '') : undefined}>
              {view === 'reviewed' ? <textarea aria-label={t(" {0}  rows {1}  columns", rowIndex, columnIndex + 1)} value={value} rows={Math.min(6, Math.max(1, value.split("\n").length))} onChange={(event) => editCell(position, columnIndex, event.target.value)} /> : <span>{value || t(" ")}</span>}
            </td>
          })}
        </tr>})}</tbody></table>
    </div>
    {column !== null && draft && <div className="clean-config-backdrop" onClick={() => setColumn(null)}>
      <aside className="clean-config-panel" aria-label={t("Column cleaning settings")} onClick={(event) => event.stopPropagation()}>
        <div className="clean-config-heading"><div><small>{t("Column cleaning rule")}</small><h2>{review.source_rows[headerIndex]?.[column] || t(" {0}  columns", column + 1)}</h2></div><button type="button" onClick={() => setColumn(null)} aria-label={t("Close settings")}><X size={18} /></button></div>
        <label>{t("Field type")}<select value={draft.kind} onChange={(event) => {
          const next = { ...draft, kind: event.target.value as ColumnRule['kind'] }; setDraft(next)
          if (next.kind !== 'choice') void applyRule(next)
        }}><option value="text">{t("Text")}</option><option value="money">{t("Amount (€)")}</option><option value="number">{t("Number")}</option><option value="date">{t("Date")}</option><option value="choice">{t("Value mapping")}</option></select></label>
        {(draft.kind === 'number' || draft.kind === 'money') && <>
          <label>{t("Source unit")}<input value={draft.source_unit} placeholder={t("e.g. T€, km")} onChange={(event) => setDraft({ ...draft, source_unit: event.target.value })} onBlur={(event) => applyOnBlur(event, draft)} /></label>
          {draft.kind === 'number' && <label>{t("Target unit")}<input value={draft.target_unit} placeholder={t("e.g. km, MVA")} onChange={(event) => setDraft({ ...draft, target_unit: event.target.value })} onBlur={(event) => applyOnBlur(event, draft)} /></label>}
          <div className="clean-config-pair"><label>{t("Decimal separator")}<select value={decimal} onChange={(event) => { const next = event.target.value as ',' | '.'; setDecimal(next); void applyRule(draft, next, thousands) }}><option value=",">{t("Comma ,")}</option><option value=".">{t("Period .")}</option></select></label>
            <label>{t("Thousands separator")}<select value={thousands} onChange={(event) => { const next = event.target.value as '.' | ',' | '' | ' '; setThousands(next); void applyRule(draft, decimal, next) }}><option value=".">{t("Period .")}</option><option value=",">{t("Comma ,")}</option><option value=" ">{t("Space")}</option><option value="">{t("None")}</option></select></label></div>
        </>}
        {draft.kind === 'choice' && <div className="clean-choice-editor">
          <div className="clean-choice-intro"><strong>{t("Map different spellings to one value")}</strong><span>{t("For example, map “under construction” and “in progress” to “in implementation”. Unmatched values are marked unresolved.")}</span></div>
          <div className="clean-choice-samples"><strong>{t("This column has  ")}{choiceValues.length} {t("  distinct source values")}</strong><span>{choiceValues.slice(0, 8).join(' · ')}{choiceValues.length > 8 ? ' …' : ''}</span>{choiceValues.length > 12 && <small>{t("This column has many values. If it is not categorical, choose Number or Text, or delete the rule.")}</small>}</div>
          {choiceEntries.map((entry, index) => <div className="clean-choice-entry" key={index}>
            <div className="clean-choice-entry-head"><strong>{t("Mapping ")}{index + 1}</strong><button type="button" aria-label={t("Delete mapping {0}", index + 1)} onClick={() => setChoiceEntries((current) => current.filter((_, position) => position !== index))}><Trash2 size={14} /> {t(" Delete")}</button></div>
            <label>{t("Normalized value")}<input value={entry.standard} placeholder={t("e.g. In progress")} onChange={(event) => setChoiceEntries((current) => current.map((item, position) => position === index ? { ...item, standard: event.target.value } : item))} /></label>
            <label>{t("Other spellings in the source table")}<textarea value={entry.aliases} rows={3} placeholder={t("Under construction\nIn progress")} onChange={(event) => setChoiceEntries((current) => current.map((item, position) => position === index ? { ...item, aliases: event.target.value } : item))} /><small>{t("Enter one spelling per line. Values identical to the normalized value match automatically.")}</small></label>
          </div>)}
          <button className="clean-choice-add" type="button" onClick={() => setChoiceEntries((current) => [...current, { standard: '', aliases: '' }])}><Plus size={14} /> {t(" Add mapping group")}</button>
        </div>}
        <button className="clean-apply-button" type="button" onClick={() => {
          const choices = draft.kind === 'choice' ? choiceMapping() : draft.choices
          if (choices !== null) void applyRule({ ...draft, choices })
        }} disabled={busy}>{t("Apply rule and recalculate")}</button>
        {configuredColumns.has(column) && <button className="clean-delete-rule" type="button" onClick={() => void deleteRule()} disabled={busy}><Trash2 size={14} /> {t(" Delete rule for this column")}</button>}
        {error && <div className="review-feedback review-error" role="status">{t(error)}</div>}
        <p>{t("Rules apply only to this cleaned version. After automatic results change, manual review will require another check.")}</p>
      </aside>
    </div>}
  </section>
}
