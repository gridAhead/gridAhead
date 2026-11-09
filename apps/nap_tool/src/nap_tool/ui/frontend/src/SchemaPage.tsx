// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Database, FileText, GitBranch } from 'lucide-react'
import { AppHeader } from './AppHeader'
import { locale, t } from './i18n'

type Column = {
  name: string
  type: string
  is_primary_key: boolean
  is_foreign_key: boolean
  is_nullable: boolean
}
type Table = { name: string; row_count: number; columns: Column[] }
type Relation = {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  kind: 'foreign_key'
}
type Schema = { tables: Table[]; relations: Relation[] }
type Line = { key: string; path: string; startX: number; startY: number; endX: number; endY: number; sameLane: boolean; fromColor: string; toColor: string }

const lanes = [
  { title: t("01 / Data sources"), tables: ['download_run', 'dso'] },
  { title: t("02 / Source documents"), tables: ['document'] },
  { title: t("03 / Table extraction"), tables: ['extract_table', 'table_type', 'extract_table_type'] },
  { title: t("04 / Data cleaning"), tables: ['clean_table'] },
  { title: t("05 / Field harmonization"), tables: ['harmonize_scheme', 'harmonize_field', 'harmonize_field_source'] },
  { title: t("06 / Sets & outputs"), tables: ['harmonize_set', 'harmonize_set_output'] },
]

const descriptions: Record<string, string> = {
  download_run: t("One CLI download run can create multiple documents"),
  dso: t("DSOs and their MaStR and BDEW IDs; each DSO has multiple documents"),
  document: t("Source PDFs, provenance, versions and selection status"),
  extract_table: t("Extracted tables and review metadata"),
  table_type: t("Available table types"),
  extract_table_type: t("One table type per extracted table"),
  clean_table: t("Each record holds automatic and reviewed CSV versions"),
  harmonize_set: t("Table subset by type, DSO and NAP round; current_scheme_id selects its current scheme"),
  harmonize_set_output: t("Generated CSV and source state for each Set / scheme pair"),
  harmonize_scheme: t("Reusable field mapping, initial set and copy source; output belongs to each set / scheme pair"),
  harmonize_field: t("Target fields and their scope in a scheme"),
  harmonize_field_source: t("Each row records a source column and its selected version"),
}

function sectionFor(table: string, column: string): string {
  if (table === 'extract_table') {
    if (column.startsWith('extract_reviewed_') || column.startsWith('extract_is_')) return t("Manual review")
    if (column.startsWith('extract_table_') || column.startsWith('extract_script') || column === 'extract_created_at') return t("Automatic extraction")
    return t("Location and selection")
  }
  if (table === 'clean_table') {
    if (column.startsWith('clear_reviewed_') || column === 'clean_is_confirmed') return t("Manual review")
    if (column.startsWith('clean_')) return t("Automatic cleaning")
    return t("Identity and selection")
  }
  if (table === 'harmonize_field_source') {
    if (['stage', 'clean_id', 'source_hash'].includes(column)) return t("Fixed version")
    return t("Source column")
  }
  return ''
}

function fieldType(column: Column): string {
  if (/^(settings|info|pages|regions|clean_config|dso_ids|years|table_settings)$|_notes$/.test(column.name)) return t("JSON")
  return column.type.replace('INTEGER', 'INT') || '—'
}

function TableCard({ table, relations }: { table: Table; relations: Relation[] }) {
  const groups = new Map<string, Column[]>()
  table.columns.forEach((column) => {
    const section = sectionFor(table.name, column.name)
    groups.set(section, [...(groups.get(section) || []), column])
  })
  const selfReferences = relations.filter((relation) => relation.from_table === table.name && relation.to_table === table.name)
  return <article className={`schema-card schema-${table.name}`} data-schema-table={table.name}>
    <div className="schema-card-heading">
      <div className="schema-card-kicker"><Database size={14} /> {t(" SQL TABLE ")}<span>{table.row_count.toLocaleString(locale === 'de' ? 'de-DE' : 'en-US')} {t("  rows")}</span></div>
      <h2>{table.name}</h2>
      <p>{descriptions[table.name]}</p>
    </div>
    <div className="schema-columns">{[...groups].map(([section, columns]) => <div key={section}>
      {section && <div className="schema-column-section">{section}</div>}
      {columns.map((column) => <div key={column.name} data-schema-column={column.name} className={`schema-column${column.is_primary_key ? ' is-pk' : ''}${column.is_foreign_key ? ' is-fk' : ''}`}>
        <strong title={column.name}>{column.name}</strong>
        <span className="schema-column-type">{fieldType(column)}</span>
        {column.is_primary_key && <b className="schema-key schema-pk">{t("PK")}</b>}
        {column.is_foreign_key && <b className="schema-key schema-fk">{t("FK")}</b>}
      </div>)}
    </div>)}</div>
    {selfReferences.length > 0 && <div className="schema-card-foot"><GitBranch size={13} /> {t(" Self-reference: ")}{selfReferences.map((item) => item.to_column).join(', ')}</div>}
  </article>
}

function drawLines(canvas: HTMLDivElement, relations: Relation[]): Line[] {
  const origin = canvas.getBoundingClientRect()
  const cards = new Map<string, DOMRect>()
  const colors = new Map<string, string>()
  const fields = new Map<string, DOMRect>()
  canvas.querySelectorAll<HTMLElement>('[data-schema-table]').forEach((card) => {
    const table = card.dataset.schemaTable || ''
    cards.set(table, card.getBoundingClientRect())
    colors.set(table, getComputedStyle(card).getPropertyValue('--schema-accent').trim() || '#6d91aa')
    card.querySelectorAll<HTMLElement>('[data-schema-column]').forEach((field) => {
      fields.set(`${table}.${field.dataset.schemaColumn}`, field.getBoundingClientRect())
    })
  })
  let verticalIndex = 0
  return relations.flatMap((relation) => {
    const fromCard = cards.get(relation.from_table)
    const toCard = cards.get(relation.to_table)
    const from = fields.get(`${relation.from_table}.${relation.from_column}`)
    const to = fields.get(`${relation.to_table}.${relation.to_column}`)
    if (!fromCard || !toCard || !from || !to) return []
    const key = `${relation.from_table}.${relation.from_column}-${relation.to_table}.${relation.to_column}`
    const startY = from.top + from.height / 2 - origin.top
    const endY = to.top + to.height / 2 - origin.top
    const sameLane = Math.abs(fromCard.left - toCard.left) < 20
    const startX = from.right - origin.left + 2
    const endX = sameLane ? to.right - origin.left + 2 : to.left - origin.left - 6
    let path: string
    if (sameLane) {
      const curveX = Math.max(fromCard.right, toCard.right) - origin.left + 20 + (verticalIndex++ % 3) * 8
      path = `M ${startX} ${startY} C ${curveX} ${startY}, ${curveX} ${endY}, ${endX} ${endY}`
    } else {
      const bend = Math.max(12, (endX - startX) * .4)
      path = `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`
    }
    return [{ key, path, startX, startY, endX, endY, sameLane,
      fromColor: colors.get(relation.from_table) || '#6d91aa',
      toColor: colors.get(relation.to_table) || '#6d91aa' }]
  })
}

export function SchemaPage() {
  const [schema, setSchema] = useState<Schema | null>(null)
  const [error, setError] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  const canvasRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.title = t("NAP Tool · Database relationships")
    fetch('/api/schema').then(async (response) => {
      if (!response.ok) throw new Error(t("Failed to load database schema({0})", response.status))
      return response.json() as Promise<Schema>
    }).then(setSchema).catch((reason: Error) => setError(reason.message))
  }, [])

  useLayoutEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !schema) return
    const update = () => setLines(drawLines(canvas, schema.relations))
    const observer = new ResizeObserver(update)
    observer.observe(canvas)
    canvas.querySelectorAll('[data-schema-table]').forEach((card) => observer.observe(card))
    update()
    return () => observer.disconnect()
  }, [schema])

  const byName = new Map(schema?.tables.map((table) => [table.name, table]) || [])
  return <div className="harmonize-page schema-page">
    <AppHeader page="schema" />
    <main className="schema-main">
      {error && <div className="harmonize-feedback error" role="status">{t(error)}</div>}
      {!schema && !error && <div className="schema-loading">{t("Loading database schema…")}</div>}
      {schema && <nav className="schema-stage-nav" aria-label={t("Schema stages")}>{[...lanes.map(lane => lane.title), t("07 / Classification files")].map((title, index) => <button type="button" key={title} onClick={() => { const lane = canvasRef.current?.querySelector<HTMLElement>(`.schema-lane-${index + 1}`); if (lane) canvasRef.current?.parentElement?.scrollTo({ left: lane.offsetLeft - 24, top: 0, behavior: 'instant' }) }}>{title}</button>)}</nav>}
      {schema && <div className="schema-scroll" role="region" tabIndex={0} aria-label={t("Database diagram; scroll horizontally")}>
        <div className="schema-canvas" ref={canvasRef}>
          <svg className="schema-wires" aria-hidden="true"><defs>{lines.map((line) => <linearGradient key={line.key} id={`schema-wire-${line.key}`} gradientUnits="userSpaceOnUse" x1={line.startX} y1={line.startY} x2={line.endX} y2={line.endY}><stop offset="0%" stopColor={line.fromColor} /><stop offset="100%" stopColor={line.toColor} /></linearGradient>)}</defs>{lines.map((line) => <g key={line.key}>
            <path className="schema-wire-fk" d={line.path} style={{ stroke: `url(#schema-wire-${line.key})` }} />
            <text className="schema-wire-label" x={line.startX + 8} y={line.startY - 6} style={{ fill: line.fromColor }}>1</text>
            <text className="schema-wire-label" x={line.sameLane ? line.endX + 8 : line.endX - 13} y={line.endY - 6} style={{ fill: line.toColor }}>{t("N")}</text>
          </g>)}</svg>
          {lanes.map((lane, index) => <div className={`schema-lane schema-lane-${index + 1}`} key={lane.title}><div className="schema-lane-title">{lane.title}</div>{lane.tables.map((name) => { const table = byName.get(name); return table ? <TableCard key={name} table={table} relations={schema.relations} /> : null })}</div>)}
          <div className="schema-lane schema-lane-7"><div className="schema-lane-title">{t("07 / Classification files")}</div>
            <article className="schema-card schema-classification-files">
              <div className="schema-card-heading"><div className="schema-card-kicker"><FileText size={14} /> {t(" FILE OUTPUT")}</div><h2>{t("nap-tool classify")}</h2><p>{t("Reads the selected set / scheme output; preserves all source columns and appends 28 derived fields.")}</p></div>
              <div className="schema-file-content"><span className="schema-column-section">{t("INPUT")}</span><code>{t("harmonize_set_output.output_path")}</code><span className="schema-column-section">{t("RULES")}</span><code>{t("config/classify.yaml")}</code><span className="schema-column-section">{t("OUTPUT DIRECTORY")}</span><code>{"classified/set_<set_id>/scheme_<scheme_id>/"}</code>
                <ul>{['classified.csv', 'validation_report.md', 'validation_report.json', 'unmapped_values.csv', 'run_manifest.json'].map(file => <li key={file}><FileText size={12} /><code>{file}</code></li>)}</ul>
                <p>{t("File artifacts in NAP_DATA_DIR. Classification does not create SQL tables or modify the harmonized source.")}</p>
              </div>
            </article>
          </div>
        </div>
      </div>}
      <div className="schema-note">{t("SQL foreign keys connect the table cards. Set.current_scheme_id selects a scheme; harmonize_set_output stores each generated pair. Classification files are stored separately in NAP_DATA_DIR.")}</div>
    </main>
  </div>
}
