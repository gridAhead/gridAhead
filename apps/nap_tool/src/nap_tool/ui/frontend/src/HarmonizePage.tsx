// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useHarmonizeSets } from './harmonizeSets'
import { useEffect, useMemo, useState } from 'react'
import type { DragEvent } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, Check, Download, GripVertical, Layers3, Plus, Search, Settings2, Trash2, X } from 'lucide-react'
import { AppHeader } from './AppHeader'

type Stage = 'clean_review' | 'clean_table' | 'extract_reviewed' | 'extract_table'
type Source = { extract_id: number; column_index: number; header: string; mode: 'auto' | 'fixed'; stage: Stage | null; clean_id: number | null; source_hash: string | null }
type Field = { key: string; title: string; scope: string; sources: Source[] }
type TableRule = { header_row: number; excluded_rows: number[] }
type Version = { stage: Stage; clean_id: number | null; hash: string; headers: string[]; samples: string[][]; row_count: number; physical_row_count: number }
type Table = { extract_id: number; document_title: string; vnb_name: string; tool: string; table_number: number; header_row: number; excluded_rows: number[]; in_set: boolean; versions: Version[] }
type CreationMode = 'copy' | 'blank' | 'lcs80' | 'lcs60'
type Scheme = { initial_set_id: number | null; id: number; name: string; updated_at: string }
type SchemeDetail = Scheme & { fields: Field[]; table_settings: Record<string, TableRule> }


const stageLabels: Record<Stage, string> = {
  clean_review: t("Cleaned tables · Reviewed version"), clean_table: t("Cleaned tables · Automatic result"),
  extract_reviewed: t("Extracted tables · Reviewed version"), extract_table: t("Extracted tables · Automatic result"),
}

async function api<T>(path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch(path, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || t("Request failed({0})", response.status))
  }
  return response.json() as Promise<T>
}

function routeScheme(): number | null {
  const value = Number(new URLSearchParams(location.search).get('scheme'))
  return Number.isInteger(value) && value > 0 ? value : null
}

function mappingPath(schemeId: number | null): string {
  return `/ui/harmonize${schemeId ? `?scheme=${schemeId}` : ''}`
}

function versionKey(version: Version): string { return `${version.stage}:${version.clean_id ?? ''}` }
function sourceKey(source: Source): string { return `${source.extract_id}:${source.column_index}` }

function bindingFor(table: Table, index: number, choice: string): Source {
  const fixed = choice !== 'auto'
  const version = fixed ? table.versions.find((item) => versionKey(item) === choice) || table.versions[0] : table.versions[0]
  return {
    extract_id: table.extract_id, column_index: index, header: version.headers[index],
    mode: fixed ? 'fixed' : 'auto', stage: fixed ? version.stage : null,
    clean_id: fixed ? version.clean_id : null, source_hash: fixed ? version.hash : null,
  }
}

export function HarmonizePage() {
  const { sets, error: setsError } = useHarmonizeSets()
  const [schemesLoaded, setSchemesLoaded] = useState(false)
  const [schemes, setSchemes] = useState<Scheme[]>([])
  const [tables, setTables] = useState<Table[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(routeScheme)
  const [detail, setDetail] = useState<SchemeDetail | null>(null)
  const [fields, setFields] = useState<Field[]>([])
  const [tableSettings, setTableSettings] = useState<Record<string, TableRule>>({})
  const [name, setName] = useState('')
  const [selectedTableId, setSelectedTableId] = useState<number | null>(null)
  const [excludeCandidate, setExcludeCandidate] = useState('')
  const [selectedFieldKey, setSelectedFieldKey] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [creationMode, setCreationMode] = useState<CreationMode>('blank')
  const [createFrom, setCreateFrom] = useState('')
  const [createInitialSetId, setCreateInitialSetId] = useState<number | null>(null)
  const [settingsInitialSetId, setSettingsInitialSetId] = useState<number | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!createOpen && !settingsOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) { setCreateOpen(false); setSettingsOpen(false) }
    }
    addEventListener('keydown', onKeyDown)
    return () => removeEventListener('keydown', onKeyDown)
  }, [createOpen, settingsOpen, busy])

  async function loadSchemes(): Promise<Scheme[]> {
    const items = await api<Scheme[]>('/api/harmonize/schemes')
    setSchemes(items); setSchemesLoaded(true)
    return items
  }

  useEffect(() => {
    document.title = t("NAP Tool · Field harmonization")
    loadSchemes()
      .then((items) => {
        if (!routeScheme() && items[0]) {
          setSelectedId(items[0].id)
          history.replaceState(null, '', mappingPath(items[0].id))
        }
      }).catch((reason: Error) => setError(reason.message))
    const onPop = () => { setCreateOpen(false); setSettingsOpen(false); setSelectedId(routeScheme()) }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    setDetail(null)
    if (!selectedId) { setTables([]); setFields([]); setTableSettings({}); return }
    let cancelled = false
    setError(''); setSelectedTableId(null)
    Promise.all([
      api<SchemeDetail>(`/api/harmonize/schemes/${selectedId}`),
      api<{ tables: Table[] }>(`/api/harmonize/inventory?scheme_id=${selectedId}`),
    ]).then(([item, inventory]) => {
      if (cancelled) return
      setDetail(item); setFields(structuredClone(item.fields)); setName(item.name)
      setTableSettings(structuredClone(item.table_settings)); setTables(inventory.tables)
      setSelectedFieldKey(item.fields[0]?.key ?? null)
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message) })
    return () => { cancelled = true }
  }, [selectedId])

  const dirty = Boolean(detail && (name !== detail.name || JSON.stringify(fields) !== JSON.stringify(detail.fields) || JSON.stringify(tableSettings) !== JSON.stringify(detail.table_settings)))
  useEffect(() => {
    if (!schemesLoaded) return
    if (!schemes.some((scheme) => scheme.id === selectedId)) {
      const nextId = schemes[0]?.id ?? null
      if (nextId !== selectedId) {
        setSelectedId(nextId)
        history.replaceState(null, '', mappingPath(nextId))
      }
    }
  }, [schemesLoaded, selectedId, schemes])

  const assigned = new Set(fields.flatMap((field) => field.sources.map(sourceKey)))
  const shownTables = useMemo(() => tables.filter((table) => table.in_set !== false &&
    `${table.vnb_name} ${table.document_title} ${table.extract_id} ${table.tool}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  ), [tables, search])
  const visibleTables = selectedTableId === null ? shownTables : shownTables.filter((table) => table.extract_id === selectedTableId)
  const unassignedColumns = visibleTables.flatMap((table) => {
    const version = table.versions[0]
    return version.headers.map((header, index) => ({ table, version, header, index }))
      .filter(({ index }) => !assigned.has(`${table.extract_id}:${index}`))
  })
  const selectedField = fields.find((field) => field.key === selectedFieldKey) || fields[0] || null
  const selectedTable = tables.find((table) => table.extract_id === selectedTableId)
  const selectedRule = selectedTable ? tableSettings[String(selectedTable.extract_id)] ?? { header_row: selectedTable.header_row, excluded_rows: selectedTable.excluded_rows } : null

  function changeTableRule(extractId: number, rule: TableRule) {
    setTableSettings((current) => ({ ...current, [String(extractId)]: rule }))
  }

  function addExcludedRow() {
    if (!selectedTable || !selectedRule) return
    const row = Number(excludeCandidate)
    if (!Number.isInteger(row) || row <= selectedRule.header_row || row > selectedTable.versions[0].physical_row_count) {
      setError(t("Excluded rows must follow the header and be within the table"))
      return
    }
    changeTableRule(selectedTable.extract_id, {
      ...selectedRule, excluded_rows: [...new Set([...selectedRule.excluded_rows, row])].sort((a, b) => a - b),
    })
    setExcludeCandidate(''); setError('')
  }

  function selectScheme(id: number, bypassDirty = false) {
    if (!bypassDirty && dirty && !confirm(t("This scheme has unsaved changes. Switch anyway?"))) return
    setCreateOpen(false); setSettingsOpen(false)
    setSelectedId(id); setNotice('')
    history.pushState(null, '', mappingPath(id))
  }

  function exportMapping() {
    if (!detail || busy) return
    const titles = fields.map((field) => field.title)
    if (new Set(titles).size !== titles.length) {
      setError(t("Duplicate target column names prevent JSON export. Give each target column a unique name first."))
      return
    }
    const mapping = Object.fromEntries(fields.map((field) => [
      field.title, [...new Set(field.sources.map((source) => source.header))],
    ]))
    const url = URL.createObjectURL(new Blob([JSON.stringify(mapping, null, 2) + '\n'], { type: 'application/json;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `harmonize_mapping_${detail.id}.json`
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setError('')
    setNotice(dirty ? t("Current mapping exported (including unsaved changes)") : t("Selected scheme mapping exported"))
  }

  async function chooseVersion(source: Source, choice: string) {
    const table = tables.find((item) => item.extract_id === source.extract_id)
    if (!table || !detail) return
    const version = choice === 'auto' ? table.versions[0] : table.versions.find((item) => versionKey(item) === choice)
    if (!version || source.column_index >= version.headers.length) return
    const next = fields.map((field) => ({
      ...field, sources: field.sources.map((item) => sourceKey(item) === sourceKey(source)
        ? bindingFor(table, source.column_index, choice) : item),
    }))
    setFields(next)
  }

  async function removeSource(source: Source) {
    const next = fields.map((field) => ({
      ...field, sources: field.sources.filter((item) => sourceKey(item) !== sourceKey(source)),
    }))
    setFields(next)
  }

  function addSource(table: Table, index: number, fieldKey: string | null) {
    const binding = bindingFor(table, index, 'auto')
    if (fieldKey === null) {
      const key = `field_${crypto.randomUUID().slice(0, 8)}`
      setFields((current) => [...current, {
        key, title: binding.header || t("Unnamed column {0}", index + 1), scope: '', sources: [binding],
      }])
      setSelectedFieldKey(key)
      return
    }
    setFields((current) => current.map((field) => field.key === fieldKey
      ? { ...field, sources: [...field.sources, binding] } : field))
    setSelectedFieldKey(fieldKey)
  }

  function dropSource(event: DragEvent, fieldKey: string | null) {
    event.preventDefault(); setDropTarget(null)
    const payload = event.dataTransfer.getData('application/x-nap-source')
    if (!payload) return
    const [tableId, index] = payload.split(':').map(Number)
    const table = tables.find((item) => item.extract_id === tableId)
    if (table && Number.isInteger(index) && !assigned.has(`${tableId}:${index}`)) addSource(table, index, fieldKey)
  }

  function moveField(index: number, direction: -1 | 1) {
    const next = [...fields]; const other = index + direction
    if (other < 0 || other >= next.length) return
    ;[next[index], next[other]] = [next[other], next[index]]
    setFields(next)
  }

  async function addField() {
    if (!detail || busy) return
    const field: Field = { key: 'field_' + crypto.randomUUID().slice(0, 8), title: t("New field"), scope: '', sources: [] }
    setFields((current) => [...current, field])
    setSelectedFieldKey(field.key)
  }

  async function save() {
    if (!detail || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/api/harmonize/schemes/${detail.id}`, 'PUT', {
        name, fields, table_settings: tableSettings, expected_updated_at: detail.updated_at,
      })
      const updated = await api<SchemeDetail>(`/api/harmonize/schemes/${detail.id}`)
      const inventory = await api<{ tables: Table[] }>(`/api/harmonize/inventory?scheme_id=${detail.id}`)
      setDetail(updated); setFields(structuredClone(updated.fields)); setName(updated.name)
      setTableSettings(structuredClone(updated.table_settings)); setTables(inventory.tables)
      await loadSchemes(); setNotice(t("Scheme saved"))
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Save failed")) }
    finally { setBusy(false) }
  }

  async function create(nameValue: string, copyFrom: number | null) {
    if (!nameValue.trim() || busy) return
    if (dirty && !confirm(t("This scheme has unsaved changes. Create and switch anyway?"))) return
    setBusy(true); setError('')
    try {
      const created = await api<{ id: number }>('/api/harmonize/schemes', 'POST', {
        name: nameValue.trim(), creation_mode: creationMode, copy_from_id: copyFrom, initial_set_id: createInitialSetId,
      })
      await loadSchemes()
      setCreateOpen(false); setCreateName(''); setCreateFrom('')
      selectScheme(created.id, true); setNotice(t("New scheme created"))
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Creation failed")) }
    finally { setBusy(false) }
  }

  async function saveInitialSet() {
    if (!detail || busy) return
    setBusy(true); setError('')
    try {
      const updated = await api<Scheme>(`/api/harmonize/schemes/${detail.id}/initial-set`, 'PUT', {
        initial_set_id: settingsInitialSetId, expected_updated_at: detail.updated_at,
      })
      setDetail({ ...detail, ...updated })
      setSettingsOpen(false)
      await loadSchemes()
      setNotice(t("Initial set saved"))
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not save set associations")) }
    finally { setBusy(false) }
  }

  function initialSetChoice(selected: number | null, change: (id: number | null) => void) {
    const compatible = sets
    return <label>{t("Initial set")}<select aria-label={t("Initial set")} value={compatible.some((set) => set.id === selected) ? selected ?? '' : ''} disabled={busy} onChange={(event) => change(event.target.value ? Number(event.target.value) : null)}>
      <option value="">{t("Choose later")}</option>{compatible.map((set) => <option key={set.id} value={set.id}>{set.name}</option>)}
    </select><small>{t("Default set on the results page. The set determines the table type and data scope.")}</small></label>
  }

  async function removeScheme() {
    if (!detail || busy || !confirm(t("Delete scheme \"{0}\", its {1} fields, and its generated CSV files in all sets?", detail.name, detail.fields.length))) return
    setBusy(true); setError('')
    try {
      const result = await api<{ deleted: boolean; deleted_fields: number }>(`/api/harmonize/schemes/${detail.id}`, 'DELETE')
      const remaining = await loadSchemes()
      setSettingsOpen(false)
      if (remaining[0]) selectScheme(remaining[0].id, true)
      else { setSelectedId(null); history.replaceState(null, '', mappingPath(null)) }
      setNotice(t("Scheme deleted; its  {0}  linked fields were removed", result.deleted_fields))
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Deletion failed")) }
    finally { setBusy(false) }
  }

  return <div className="harmonize-page harmonize-mapping-page">
    <AppHeader page="harmonize" schemeId={selectedId} beforeNavigate={() => !dirty || confirm(t("This scheme has unsaved changes. Leave anyway?"))} />
    {(error || notice) && <div className={`harmonize-feedback ${error ? 'error' : ''}`} role="status">{t(error || notice)}<button type="button" onClick={() => { setError(''); setNotice('') }} aria-label={t("Dismiss notice")}><X size={13} /></button></div>}
    <main className="harmonize-layout harmonize-mapping-layout">
      <aside className="harmonize-schemes">
        <div className="harmonize-panel-title"><span>{t("01 / Scheme")}</span><strong>{t("Scheme list")}</strong></div>
        {setsError && <small className="harmonize-sets-error" role="alert">{t(setsError)}</small>}
        {schemesLoaded && !schemes.length && <div className="harmonize-no-schemes">{t("No schemes yet. Create one to start mapping.")}</div>}
        <div className="harmonize-scheme-list">{schemes.map((scheme) => {
          const initialSet = sets.find((set) => set.id === scheme.initial_set_id)?.name
          return <button key={scheme.id} type="button" className={`harmonize-scheme ${selectedId === scheme.id ? 'selected' : ''}`} onClick={() => selectScheme(scheme.id)}>
            <span className="harmonize-scheme-icon"><Layers3 size={14} /></span>
            <span><strong title={scheme.name}>{scheme.name}</strong>
              <small>{t("Custom scheme")}</small>
              <small className="harmonize-scheme-sets" title={initialSet || t("No initial set")}>{t("Initial set: ")}{initialSet || '—'}</small>
            </span>
            {selectedId === scheme.id && <Check size={13} />}
          </button>
        })}</div>
        <div className="harmonize-scheme-management"><button type="button" title={t("New scheme")} onClick={() => { setCreationMode('blank'); setCreateFrom(''); setCreateInitialSetId(null); setCreateOpen(true); setSettingsOpen(false) }}><Plus size={14} /> {t(" New")}</button>
          <button className="harmonize-settings-trigger" type="button" title={t("Scheme settings")} onClick={() => { setSettingsInitialSetId(detail?.initial_set_id ?? null); setSettingsOpen(true); setCreateOpen(false) }} disabled={!detail}><Settings2 size={14} /> {t(" Settings")}</button>
          <button type="button" title={t("Export mapping JSON")} onClick={exportMapping} disabled={!detail || busy}><Download size={14} /> {t(" JSON")}</button>
          {<button className="harmonize-sidebar-save" type="button" title={t("Save scheme")} onClick={() => void save()} disabled={!detail || busy || !dirty}><Check size={14} /> {t(" Save")}</button>}
          <a className="harmonize-scheme-result-link" aria-label={t("View results")} title={t("View results")} href={'/ui/harmonize/result' + (selectedId ? '?scheme=' + selectedId : '')} onClick={(event) => { if (dirty && !confirm(t("This scheme has unsaved changes. View results anyway?"))) event.preventDefault() }}><ArrowRight size={14} /></a>
        </div>
      </aside>

      {createOpen && <div className="harmonize-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setCreateOpen(false) }}>
        <div className="harmonize-modal" role="dialog" aria-modal="true" aria-labelledby="harmonize-create-title">
          <button className="harmonize-modal-close" type="button" aria-label={t("Close new scheme")} onClick={() => setCreateOpen(false)} disabled={busy}><X size={18} /></button>
          <h2 id="harmonize-create-title">{t("New scheme")}</h2>
          <div className="harmonize-modal-form">
            <label>{t("New scheme name")}<input autoFocus value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder={t("Enter scheme name")} /></label>
            <label>{t("Creation method")}<select aria-label={t("Creation method")} value={creationMode} onChange={(event) => { setCreationMode(event.target.value as CreationMode); setCreateFrom('') }}>
              <option value="copy" disabled={!schemes.length}>{t("Copy an existing scheme")}</option>
              <option value="blank">{t("Blank scheme")}</option>
              <option value="lcs80">{t("Generate with LCS 80%")}</option>
              <option value="lcs60">{t("Generate with LCS 60%")}</option>
            </select></label>
            {creationMode === 'copy' && <label>{t("Start from an existing scheme")}<select aria-label={t("Source scheme")} value={createFrom} onChange={(event) => setCreateFrom(event.target.value)}><option value="" disabled>{t("Select a scheme")}</option>{schemes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
            {(creationMode === 'lcs80' || creationMode === 'lcs60') && <small>{t("Group matching column headers automatically. You can edit the generated fields after creation.")}</small>}
            {initialSetChoice(createInitialSetId, setCreateInitialSetId)}
            {createFrom && <small>{t("A copied scheme keeps the original table type.")}</small>}
          </div>
          <div className="harmonize-modal-actions"><button type="button" onClick={() => setCreateOpen(false)} disabled={busy}>{t("Cancel")}</button><button className="harmonize-primary" type="button" disabled={!createName.trim() || busy || (creationMode === 'copy' && !createFrom)} onClick={() => create(createName, createFrom ? Number(createFrom) : null)}>{t("Create")}</button></div>
        </div>
      </div>}
      {settingsOpen && detail && <div className="harmonize-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setSettingsOpen(false) }}>
        <div className="harmonize-modal" role="dialog" aria-modal="true" aria-labelledby="harmonize-settings-title">
          <button className="harmonize-modal-close" type="button" aria-label={t("Close scheme settings")} onClick={() => setSettingsOpen(false)} disabled={busy}><X size={18} /></button>
          <h2 id="harmonize-settings-title">{t("Scheme settings")}</h2>
          <div className="harmonize-modal-form">
            <label>{t("Scheme name")}<input value={name} readOnly /></label>
            {initialSetChoice(settingsInitialSetId, setSettingsInitialSetId)}
            <button type="button" className="harmonize-primary" disabled={busy || settingsInitialSetId === detail.initial_set_id} onClick={() => void saveInitialSet()}>{t("Save initial set")}</button>
          </div>
          <div className="harmonize-modal-actions">{<button className="harmonize-danger" type="button" disabled={busy} onClick={() => void removeScheme()}><Trash2 size={13} /> {t(" Delete")}</button>}</div>
        </div>
      </div>}

      <section className="harmonize-unmapped">
        <div className="harmonize-panel-title"><span>{t("02 / To process")}</span><strong>{t("Unmapped fields ")}<em>{unassignedColumns.length}</em></strong></div>
        <label className="harmonize-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search DSOs, documents or tables")} /></label>
        <select className="harmonize-table-select" aria-label={t("Filter by table")} value={selectedTableId ?? ''} onChange={(event) => setSelectedTableId(event.target.value ? Number(event.target.value) : null)}>
          <option value="">{t("All tables")}</option>
          {shownTables.map((table) => <option key={table.extract_id} value={table.extract_id}>{table.vnb_name} {t(" · Table #")}{table.extract_id}</option>)}
        </select>
        {selectedTable && selectedRule && <div className="harmonize-row-rules">
          <strong>{t("Table row settings")}</strong>
          <label>{t("Header row")}<input type="number" min={1} max={selectedTable.versions[0].physical_row_count} value={selectedRule.header_row}
              onChange={(event) => { const row = Number(event.target.value); if (Number.isInteger(row) && row >= 1) changeTableRule(selectedTable.extract_id, { ...selectedRule, header_row: row }) }} />
          </label>
          <small>{t(" ")}{selectedRule.header_row} {t("  is used for column names; preceding rows are excluded. Save the scheme to refresh the pending columns.")}</small>
          <label>{t("Exclude later header or total rows")}<span className="harmonize-row-add"><input type="number" min={selectedRule.header_row + 1} max={selectedTable.versions[0].physical_row_count} value={excludeCandidate} onChange={(event) => setExcludeCandidate(event.target.value)} placeholder={t("CSV row number")} /><button type="button" onClick={addExcludedRow}>{t("Add")}</button></span>
          </label>
          {!!selectedRule.excluded_rows.length && <div className="harmonize-excluded-rows">{selectedRule.excluded_rows.map((row) => <button key={row} type="button" title={t("Include row {0} again", row)} onClick={() => changeTableRule(selectedTable.extract_id, { ...selectedRule, excluded_rows: selectedRule.excluded_rows.filter((item) => item !== row) })}>{t(" ")}{row} {t("  rows ×")}</button>)}</div>}
        </div>}
        <p className="harmonize-drag-hint">{t("Drag columns to the target fields on the right. All unmapped columns in the current filter are listed here.")}</p>
        <div className="harmonize-unmapped-list">
          {unassignedColumns.map(({ table, version, header, index }) => <article className="harmonize-unmapped-card" key={table.extract_id + ':' + index} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('application/x-nap-source', table.extract_id + ':' + index) }}>
            <GripVertical size={15} />
            <div><small>{table.vnb_name} {t(" · Table #")}{table.extract_id} {t(" ·  columns ")}{index + 1}</small>
              <div className="harmonize-unmapped-heading"><strong title={header || t("Unnamed column ") + (index + 1)}>{header || t("Unnamed column ") + (index + 1)}</strong>
                <select aria-label={(header || t(" ") + (index + 1) + t("  columns")) + t("Map to target field")} value=""  onChange={(event) => addSource(table, index, event.target.value === '__new' ? null : event.target.value)}>
                  <option value="">{t("Map to…")}</option><option value="__new">{t("+ New target field")}</option>
                  {fields.map((field) => <option key={field.key} value={field.key}>{field.title}</option>)}
                </select>
              </div><div className="harmonize-unmapped-samples"><small>{t("Sample data")}</small>{version.samples[index]?.length ? version.samples[index].map((value, at) => <span key={at} title={value}>{value}</span>) : <span>{t("No nonempty values")}</span>}</div>
            </div>
          </article>)}
          {!unassignedColumns.length && <div className="harmonize-empty">{t("No unmapped columns in the current filter.")}</div>}
        </div>
      </section>
      <section className="harmonize-fields harmonize-mapped">
        <div className="harmonize-panel-title"><span>{t("03 / Fields")}</span><strong>{t("Mapped fields ")}<em>{fields.length}</em></strong><button className="harmonize-add-field" type="button" onClick={() => void addField()} disabled={!detail || busy}><Plus size={13} /> {t(" Add field")}</button></div>
        <div className="harmonize-field-list">
          {fields.map((field, index) => <article className={'harmonize-field-card harmonize-field-summary' + (selectedField?.key === field.key ? ' selected' : '') + (dropTarget === field.key ? ' drop-active' : '')} key={field.key}
            onDragOver={(event) => { { event.preventDefault(); setDropTarget(field.key) } }}
            onDragLeave={() => setDropTarget(null)} onDrop={(event) => dropSource(event, field.key)}>
            <button className="harmonize-field-select" type="button" onClick={() => setSelectedFieldKey(field.key)} aria-label={t("View ") + field.title + t(" mapping details")}>
              <span>{String(index + 1).padStart(2, '0')}</span><strong>{field.title}</strong><em>{t("(")}{field.sources.length}{t(")")}</em><ArrowRight size={14} />
            </button>
          </article>)}
          {!fields.length && <div className="harmonize-empty">{t("No target fields yet. Drag a pending column below or add a target field.")}</div>}
          {<div className={'harmonize-new-drop' + (dropTarget === '__new' ? ' drop-active' : '')} onDragOver={(event) => { event.preventDefault(); setDropTarget('__new') }} onDragLeave={() => setDropTarget(null)} onDrop={(event) => dropSource(event, null)}><Plus size={16} /> {t(" Drop here to create a target field")}</div>}
        </div>
      </section>
      <section className="harmonize-details">
        <div className="harmonize-panel-title"><span>{t("04 / Details")}</span><strong>{t("Mapping details ")}<em>{selectedField?.sources.length ?? 0}</em></strong></div>
        {selectedField ? <>
          <div className="harmonize-detail-heading">
            <label>{t("Target field")}<input aria-label={t("Target field name")} value={selectedField.title}  onChange={(event) => setFields((current) => current.map((item) => item.key === selectedField.key ? { ...item, title: event.target.value } : item))} /></label>
            <div className="harmonize-detail-controls"><button type="button" aria-label={t("Move field up")} disabled={fields.indexOf(selectedField) === 0} onClick={() => moveField(fields.indexOf(selectedField), -1)}><ArrowUp size={14} /></button><button type="button" aria-label={t("Move field down")} disabled={fields.indexOf(selectedField) === fields.length - 1} onClick={() => moveField(fields.indexOf(selectedField), 1)}><ArrowDown size={14} /></button><button type="button" aria-label={t("Delete field")}  onClick={() => { setFields((current) => current.filter((item) => item.key !== selectedField.key)); setSelectedFieldKey(null) }}><X size={14} /></button></div>
          </div>
          <input className="harmonize-scope" aria-label={t("Scope")} placeholder={t("Scope or note (optional)")} value={selectedField.scope}  onChange={(event) => setFields((current) => current.map((item) => item.key === selectedField.key ? { ...item, scope: event.target.value } : item))} />
          <div className="harmonize-detail-list">{selectedField.sources.map((source) => {
            const table = tables.find((item) => item.extract_id === source.extract_id)
            const version = table?.versions.find((item) => item.stage === source.stage && item.clean_id === source.clean_id && source.mode === 'fixed') || table?.versions[0]
            return <article className="harmonize-detail-row" key={sourceKey(source)}>
              <div className="harmonize-detail-top">
                <div className="harmonize-detail-source"><strong title={source.header}>{source.header}</strong><small>{table?.vnb_name || t("Unknown DSO")} {t(" · Table #")}{source.extract_id} {t(" ·  columns ")}{source.column_index + 1}</small></div>
                <select aria-label={source.header + t(" · Table #") + source.extract_id + t(" Source version")} value={source.mode === 'auto' ? 'auto' : source.stage + ':' + (source.clean_id ?? '')} disabled={busy || !table} onChange={(event) => void chooseVersion(source, event.target.value)}>
                  <option value="auto">{t("Choose automatically")}</option>
                  {table?.versions.filter((item) => source.column_index < item.headers.length).map((item) => <option key={versionKey(item)} value={versionKey(item)}>{stageLabels[item.stage]}{item.clean_id ? ' #' + item.clean_id : ''}</option>)}
                </select>
                <button type="button" className="harmonize-unlink" aria-label={source.header + t(" · Table #") + source.extract_id + t(" Remove link")} title={t("Remove link")} disabled={busy} onClick={() => void removeSource(source)}><Trash2 size={13} /> {t(" Delete")}</button>
              </div>
              <div className="harmonize-detail-samples"><small>{t("Sample data")}</small>{version?.samples[source.column_index]?.length ? version.samples[source.column_index].map((value, at) => <span key={at}>{value}</span>) : <span>{t("No nonempty values")}</span>}</div>
            </article>
          })}{!selectedField.sources.length && <div className="harmonize-empty">{t("No source columns linked yet. Drag a column from the left onto this field.")}</div>}</div>
        </> : <div className="harmonize-empty">{t("Select a mapped field to see its sources and sample data.")}</div>}
      </section>
    </main>
  </div>
}
