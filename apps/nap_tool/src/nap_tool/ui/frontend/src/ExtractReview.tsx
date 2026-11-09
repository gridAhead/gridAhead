// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useTableTypes } from './tableTypes'
import { lazy, Suspense, useEffect, useState } from 'react'
import { Archive, ArchiveX, ArrowLeft, Check, ChevronDown, CircleCheck, FileText, MessageSquareText, Plus, Save, Table2 } from 'lucide-react'
import { locale, t } from './i18n'

const PdfPage = lazy(() => import('./PdfPage').then((module) => ({ default: module.PdfPage })))

type ReviewData = {
  id: number
  tool: string
  table_number: number
  document_title: string
  pages: number[]
  regions: { page: number; bbox: number[] | null }[]
  rows: string[][]
  source_rows: string[][]
  reviewed_rows: string[][] | null
  source_hash: string
  reviewed_hash: string | null
  is_confirmed: boolean
  table_type: number | null
  is_archived: boolean
  note: string
  is_stale: boolean
  has_pdf: boolean
}

type ReviewProps = {
  extractId: number
  onClose: () => void
  onSaved: () => void
}

type MetadataChange = { table_type?: number | null; is_archived?: boolean; note?: string }

function sameGrid(left: string[][], right: string[][]): boolean {
  return left.length === right.length && left.every((row, rowIndex) =>
    row.length === right[rowIndex].length && row.every((value, columnIndex) => value === right[rowIndex][columnIndex]),
  )
}

export function ExtractReview({ extractId, onClose, onSaved }: ReviewProps) {
  const { types: tableTypes, error: tableTypesError } = useTableTypes()
  const [review, setReview] = useState<ReviewData | null>(null)
  const [rows, setRows] = useState<string[][]>([])
  const [tableView, setTableView] = useState<'source' | 'reviewed'>('reviewed')
  const [page, setPage] = useState<number | null>(null)
  const [zoom, setZoom] = useState(1)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const [noteDraft, setNoteDraft] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setNotice(null)
    setReview(null)
    setNoteOpen(false)
    fetch(`/api/extract-review/${extractId}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(t("Failed to load review data({0})", response.status))
        return response.json() as Promise<ReviewData>
      })
      .then((data) => {
        setReview(data)
        setRows(data.rows)
        setTableView('reviewed')
        setNoteDraft(data.note)
        setPage(data.pages[0] ?? 1)
        setZoom(1)
        setDirty(false)
        setLoading(false)
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : t("Failed to load review data"))
        setLoading(false)
      })
    return () => controller.abort()
  }, [extractId])

  useEffect(() => {
    if (!dirty && (!noteOpen || noteDraft === review?.note)) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, noteOpen, noteDraft, review?.note])

  function changeCell(rowIndex: number, columnIndex: number, value: string) {
    const updated = rows.map((row, index) =>
      index === rowIndex
        ? Array.from({ length: columnCount }, (_, column) => column === columnIndex ? value : row[column] ?? '')
        : row,
    )
    setRows(updated)
    setDirty(!sameGrid(updated, review?.rows ?? []))
    setNotice(null)
  }

  function addRow() {
    setRows((previous) => [...previous, Array.from({ length: columnCount }, () => '')])
    setDirty(true)
  }

  function addColumn() {
    setRows((previous) => previous.map((row) => [
      ...Array.from({ length: columnCount }, (_, column) => row[column] ?? ''),
      '',
    ]))
    setDirty(true)
  }

  async function save(confirm: boolean) {
    if (!review || saving || tableView === 'source') return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const response = await fetch(`/api/extract-review/${extractId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rows,
          source_hash: review.source_hash,
          reviewed_hash: review.reviewed_hash,
          confirm,
        }),
      })
      if (!response.ok) {
        const body = await response.json() as { detail?: string }
        throw new Error(body.detail || t("Save failed({0})", response.status))
      }
      const result = await response.json() as { reviewed_hash: string; is_confirmed: boolean }
      setReview({ ...review, rows, reviewed_rows: rows, reviewed_hash: result.reviewed_hash, is_confirmed: result.is_confirmed, is_stale: false })
      setDirty(false)
      setNotice(confirm ? t("Extraction saved and confirmed") : review.is_confirmed && !dirty ? t("Extraction confirmation revoked") : t("Review draft saved"))
      onSaved()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Save failed"))
    } finally {
      setSaving(false)
    }
  }

  async function updateMetadata(change: MetadataChange, message: string): Promise<boolean> {
    if (!review || saving) return false
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const response = await fetch(`/api/extract-review/${extractId}/metadata`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...change,
          source_hash: review.source_hash,
          reviewed_hash: review.reviewed_hash,
        }),
      })
      if (!response.ok) {
        const body = await response.json() as { detail?: string }
        throw new Error(body.detail || t("Update failed({0})", response.status))
      }
      const result = await response.json() as Pick<ReviewData, 'table_type' | 'is_archived' | 'note'>
      setReview({ ...review, ...result })
      setNoteDraft(result.note)
      setNoteOpen(false)
      setNotice(message)
      onSaved()
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Update failed"))
      return false
    } finally {
      setSaving(false)
    }
  }

  async function toggleArchived() {
    if (!review) return
    if (!review.is_archived && !window.confirm(
      t("Discarding archives this extracted table. The source file and review record remain. {0}Discard it?", dirty ? t("Unsaved table edits will be lost. ") : ''),
    )) return
    const archived = !review.is_archived
    const updated = await updateMetadata(
      { is_archived: archived }, archived ? t("Extracted table archived") : t("Extracted table restored"),
    )
    if (updated && archived) {
      setRows(review.rows)
      setDirty(false)
    }
  }

  function close() {
    if ((dirty || (noteOpen && noteDraft !== review?.note)) && !window.confirm(t("You have unsaved changes. Return anyway?"))) return
    onClose()
  }

  const sourceRows = review?.source_rows ?? []
  const columnCount = Math.max(1, ...rows.map((row) => row.length), ...sourceRows.map((row) => row.length))
  const displayRows = tableView === 'source' ? sourceRows : rows
  const displayRowCount = Math.max(sourceRows.length, rows.length)
  let diffCount = 0
  for (let rowIndex = 0; rowIndex < displayRowCount; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
      if (sourceRows[rowIndex]?.[columnIndex] !== rows[rowIndex]?.[columnIndex]) diffCount += 1
    }
  }
  const pages = review?.pages ?? []
  const confirmed = Boolean(review?.is_confirmed && !dirty && !review.is_stale)

  return <section className="review-workspace" aria-label={t("Extracted tablesManual review")}>
    {loading ? <div className="review-message"><span>{t("Loading PDF and extracted table…")}</span><button className="review-close" type="button" onClick={close}><ArrowLeft size={14} /> {t(" Back to overview")}</button></div> : error && !review ?
      <div className="review-message review-error"><span>{t(error)}</span><button className="review-close" type="button" onClick={close}><ArrowLeft size={14} /> {t(" Back to overview")}</button></div> : review && <>
      <div className="review-pdf-section">
        <div className="review-section-bar">
          <span><FileText size={17} /> {t(" Source PDF ")}<button className="review-close" type="button" onClick={close}><ArrowLeft size={14} /> {t(" Back to overview")}</button></span>
          <div className="review-page-select">
            {pages.length > 0 && <label>{t("Go to page ")}<select value={page ?? pages[0]} onChange={(event) => setPage(Number(event.target.value))}>
              {pages.map((item) => <option key={item} value={item}>{locale === 'de' ? 'Seite' : t("Page")} {item}</option>)}
            </select><ChevronDown size={14} /></label>}
            <label>{t("Zoom ")}<select aria-label={t("PDF zoom")} value={zoom} onChange={(event) => setZoom(Number(event.target.value))}>
              <option value={1}>{t("Fit width")}</option>
              <option value={1.5}>{t("150%")}</option>
              <option value={2}>{t("200%")}</option>
            </select><ChevronDown size={14} /></label>
            <a href={`/api/extract-review/${extractId}/pdf`} target="_blank" rel="noreferrer">{t("Open original PDF")}</a>
          </div>
        </div>
        {review.has_pdf ? <Suspense fallback={<div className="review-empty-pdf">{t("Loading PDF…")}</div>}><PdfPage extractId={extractId} page={page ?? 1} zoom={zoom} regions={review.regions} /></Suspense> :
          <div className="review-empty-pdf">{t("No PDF is available for this document")}</div>}
      </div>

      <div className="review-table-section">
        <div className="review-section-bar review-table-bar">
          <div className="review-table-heading">
            <span><Table2 size={17} /> {t(" tables ")}<small>{displayRows.length} {t("  rows · ")}{columnCount} {t("  columns")}</small></span>
            <div className="review-table-switch" role="group" aria-label={t("Table versions")}>
              <button type="button" aria-pressed={tableView === 'source'} onClick={() => setTableView('source')}>{t("Automatic extraction")}</button>
              <button type="button" aria-pressed={tableView === 'reviewed'} onClick={() => setTableView('reviewed')}>{t("Manual review")}{review.reviewed_hash === null ? t(" · Unsaved") : ''}</button>
            </div>
            <small className={diffCount > 0 ? 'review-diff-count has-diff' : 'review-diff-count'}>{diffCount} {t("  differences")}</small>
          </div>
          <div className="review-actions">
            <button type="button" className="review-light-button" onClick={addRow} disabled={tableView === 'source'}><Plus size={14} /> {t(" Add row")}</button>
            <button type="button" className="review-light-button" onClick={addColumn} disabled={tableView === 'source'}><Plus size={14} /> {t(" Add column")}</button>
            <button type="button" className={`review-save-button ${review.reviewed_hash && !dirty && !review.is_confirmed ? 'is-complete' : ''}`} onClick={() => save(false)} disabled={saving || tableView === 'source' || (!dirty && review.reviewed_hash !== null)}>{review.reviewed_hash && !dirty && !review.is_confirmed ? <CircleCheck size={14} /> : <Save size={14} />} {review.reviewed_hash && !dirty && !review.is_confirmed ? t("Draft saved") : t("Save draft")}</button>
            <button type="button" className={`review-confirm-button ${confirmed ? 'is-complete' : ''}`} onClick={() => save(!confirmed)} disabled={saving || tableView === 'source'} aria-pressed={confirmed} title={confirmed ? t("Click to revoke confirmation") : t("Save and confirm extraction")}>{confirmed ? <CircleCheck size={15} /> : <Check size={15} />} {confirmed ? t("Confirmed") : t("Save and confirm")}</button>
            <label className="review-table-type">{t("Table type")}<select title={t(tableTypesError || undefined)} aria-label={t("Table type")} value={review.table_type ?? ''} disabled={saving} onChange={(event) => {
                const tableType = event.target.value ? Number(event.target.value) as number : null
                void updateMetadata({ table_type: tableType }, t("Table type updated"))
              }}>
                <option value="">{t("No table type")}</option>
                {tableTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
              </select>
            </label>
            <button type="button" className={`review-discard-button ${review.is_archived ? 'is-archived' : ''}`} onClick={toggleArchived} disabled={saving}>{review.is_archived ? <ArchiveX size={14} /> : <Archive size={14} />} {review.is_archived ? t("Discarded · Restore") : t("Discard")}</button>
            <button type="button" className={`review-note-button ${review.note ? 'has-note' : ''}`} onClick={() => { setNoteDraft(review.note); setNoteOpen(!noteOpen) }} disabled={saving} aria-expanded={noteOpen}>{review.note ? <CircleCheck size={14} /> : <MessageSquareText size={14} />} {review.note ? t("Note saved") : t("Note")}</button>
          </div>
        </div>
        {noteOpen && <div className="review-note-panel">
          <label htmlFor="extract-review-note">{t("Manual review notes")}</label>
          <textarea id="extract-review-note" value={noteDraft} maxLength={5000} rows={2} placeholder={t("Note items to check or reasons for review…")} onChange={(event) => setNoteDraft(event.target.value)} />
          <div><button type="button" onClick={() => { setNoteDraft(review.note); setNoteOpen(false) }}>{t("Cancel")}</button><button type="button" className="review-note-save" onClick={() => updateMetadata({ note: noteDraft }, t("Note saved"))} disabled={saving}>{t("Save note")}</button></div>
        </div>}
        {(review.is_stale || error || notice) && <div className={`review-feedback ${error ? 'review-error' : ''}`} role="status">
          {error || notice || t("Extraction source changed; check the table and save again.")}
        </div>}
        <div className="review-grid-wrap">
          <table className="review-grid"><tbody>
            {Array.from({ length: displayRowCount }, (_, rowIndex) => <tr key={rowIndex}>
              <th scope="row">{rowIndex + 1}</th>
              {Array.from({ length: columnCount }, (_, columnIndex) => {
                const different = sourceRows[rowIndex]?.[columnIndex] !== rows[rowIndex]?.[columnIndex]
                const row = displayRows[rowIndex]
                return <td key={columnIndex} className={different ? 'review-diff-cell' : undefined}>
                  {row === undefined ? <span className="review-missing-cell">—</span> : <textarea
                    aria-label={t("Row {0}, column {1}{2}", rowIndex + 1, columnIndex + 1, different ? t(", differs from the other version") : '')}
                    value={row[columnIndex] ?? ''}
                    readOnly={tableView === 'source'}
                    onChange={tableView === 'reviewed' ? (event) => changeCell(rowIndex, columnIndex, event.target.value) : undefined}
                    rows={1}
                  />}
                </td>
              })}
            </tr>)}
          </tbody></table>
        </div>
      </div>
    </>}
  </section>
}
