// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2, X } from 'lucide-react'
import { setsApi, useHarmonizeSets, type HarmonizeSet, type SetCounts, type SetOptions } from './harmonizeSets'
import type { TableType } from './tableTypes'

function selectedIds(select: HTMLSelectElement): number[] {
  return Array.from(select.selectedOptions, (option) => Number(option.value))
}

export function SetsSettings({ types, onChanged }: { types: TableType[]; onChanged: () => void }) {
  const { sets, loading, error: listError, reload } = useHarmonizeSets()
  const [options, setOptions] = useState<SetOptions>({ vnbs: [], years: [] })
  const [optionsError, setOptionsError] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [typeId, setTypeId] = useState<number | null>(null)
  const [dsoIds, setDsoIds] = useState<number[]>([])
  const [years, setYears] = useState<number[]>([])
  const [extraYear, setExtraYear] = useState('')
  const [counts, setCounts] = useState<SetCounts | null>(null)
  const [countError, setCountError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setsApi<SetOptions>('/options', 'GET', undefined, controller.signal)
      .then((items) => { setOptions(items); setOptionsError('') })
      .catch((reason) => { if (!controller.signal.aborted) setOptionsError(String(reason)) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!types.some((type) => type.id === typeId)) setTypeId(types[0]?.id ?? null)
  }, [types, typeId])

  useEffect(() => {
    setCounts(null); setCountError('')
    if (!open || typeId === null) return
    const controller = new AbortController()
    setsApi<SetCounts>('/preview', 'POST', { table_type_id: typeId, dso_ids: dsoIds, years }, controller.signal)
      .then(setCounts)
      .catch((reason) => { if (!controller.signal.aborted) setCountError(String(reason)) })
    return () => controller.abort()
  }, [open, typeId, dsoIds, years])

  async function save() {
    if (!name.trim() || typeId === null || busy) return
    setBusy(true); setError('')
    try {
      await setsApi(editingId ? `/${editingId}` : '', editingId ? 'PUT' : 'POST', { name: name.trim(), table_type_id: typeId, dso_ids: dsoIds, years })
      setNotice(editingId ? t("Set saved. If filters changed, regenerate its harmonized results before classification.") : t("Set created.")); setEditingId(null)
      setOpen(false); setName(''); setDsoIds([]); setYears([]); setExtraYear('')
      reload(); onChanged()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not save set")) }
    finally { setBusy(false) }
  }

  async function remove(set: HarmonizeSet) {
    if (busy || !window.confirm(t("Delete set \"{0}\" and its generated CSV files? Schemes will be kept.", set.name))) return
    setBusy(true); setError('')
    try { await setsApi(`/${set.id}`, 'DELETE'); reload(); onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not delete set")) }
    finally { setBusy(false) }
  }

  function edit(set: HarmonizeSet) {
    setEditingId(set.id); setName(set.name); setTypeId(set.table_type_id)
    setDsoIds([...set.dso_ids]); setYears([...set.years]); setExtraYear(''); setError(''); setNotice(''); setOpen(true)
    setOptions(current => ({ ...current, years: [...new Set([...current.years, ...set.years])].sort((a, b) => b - a) }))
    document.querySelector('.settings-sets')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  function newSet() {
    setEditingId(null); setName(''); setTypeId(types[0]?.id ?? null); setDsoIds([]); setYears([])
    setExtraYear(''); setError(''); setNotice(''); setOpen(true)
  }

  function addYear() {
    const year = Number(extraYear)
    if (!Number.isInteger(year) || year < 2000 || year > 2100) return
    setOptions((current) => ({ ...current, years: [...new Set([...current.years, year])].sort((a, b) => b - a) }))
    setYears((current) => [...new Set([...current, year])]); setExtraYear('')
  }

  return <section className="settings-card settings-sets" aria-label={t("Sets")}>
    <div className="settings-section-heading"><div><h2>{t("Sets ")}<span className="pane-count">{sets.length}</span></h2><p>{t("Choose the tables to include by type, DSO and NAP round.")}</p></div>
      <button type="button" className="settings-primary" onClick={newSet} disabled={busy || !types.length}><Plus size={14} /> {t(" New set")}</button>
    </div>
    {(error || listError || optionsError) && <p className="review-error" role="alert">{t(error || listError || optionsError)}</p>}
    {notice && <p role="status">{t(notice)}</p>}
    {open && <h3>{editingId ? t("Edit set") : t("New set")}</h3>}
    {open && <form className="settings-set-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <label>{t("Set name")}<input autoFocus value={name} maxLength={200} required disabled={busy} onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Grid measures 2024")} /></label>
      <label>{t("Table type")}<select value={typeId ?? ''} disabled={busy} onChange={(event) => setTypeId(Number(event.target.value))}>{types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
      <label>{t("DSOs")}<select multiple size={5} value={dsoIds.map(String)} disabled={busy || !!optionsError} onChange={(event) => setDsoIds(selectedIds(event.target))}>{options.vnbs.map((vnb) => <option key={vnb.id} value={vnb.id}>{vnb.name}</option>)}</select><small>{dsoIds.length ? `${dsoIds.length} selected` : t("All DSOs")} {t(" · Leave empty to include all.")}</small><button type="button" onClick={() => setDsoIds([])} disabled={busy || !dsoIds.length}>{t("All DSOs")}</button></label>
      <label>{t("NAP rounds")}<select multiple size={5} value={years.map(String)} disabled={busy || !!optionsError} onChange={(event) => setYears(selectedIds(event.target))}>{options.years.map((year) => <option key={year} value={year}>{year}</option>)}</select><small>{years.length ? years.join(', ') : t("All years")} {t(" · Leave empty to include all.")}</small><button type="button" onClick={() => setYears([])} disabled={busy || !years.length}>{t("All years")}</button></label>
      <div className="settings-add-year"><label>{t("Additional year")}<input type="number" min={2000} max={2100} value={extraYear} disabled={busy} onChange={(event) => setExtraYear(event.target.value)} placeholder={t("2024")} /></label><button type="button" onClick={addYear} disabled={busy || !extraYear || Number(extraYear) < 2000 || Number(extraYear) > 2100}>{t("Add year")}</button></div>
      <div className="settings-set-preview" role="status">
        {countError ? <span className="review-error">{t(countError)}</span> : counts ? <>
          <strong>{counts.table_count} {t(" tables · ")}{counts.vnb_count} {t(" DSOs")}</strong>
          {counts.table_count === 0 && <span className="settings-zero">{t("No matching tables yet. You can still create this set.")}</span>}
          {counts.undated_document_count > 0 && <span>{counts.undated_document_count} {t(" documents have no year")}{years.length ? t(" and are excluded.") : t(" and are included.")}</span>}
        </> : t("Counting matching tables…")}
      </div>
      <div className="settings-set-actions"><button type="button" disabled={busy} onClick={() => setOpen(false)}><X size={14} /> {t(" Cancel")}</button><button className="settings-primary" type="submit" disabled={busy || !name.trim() || typeId === null || !!optionsError || !!countError}>{busy ? t("Saving…") : editingId ? t("Save changes") : t("Create set")}</button></div>
    </form>}
    <div className="settings-set-list">
      {loading && <p role="status">{t("Loading sets…")}</p>}
      {!loading && !sets.length && !listError && <p>{t("No sets yet. Create one to define a table subset.")}</p>}
      {sets.map((set) => <div className="settings-type" key={set.id}>
        <div><strong>{set.name}</strong><small>{types.find((type) => type.id === set.table_type_id)?.name} · {set.dso_ids.length ? set.dso_ids.map((id) => options.vnbs.find((vnb) => vnb.id === id)?.name ?? `DSO #${id}`).join(', ') : t("All DSOs")} · {set.years.length ? set.years.join(', ') : t("All years")}</small><small>{set.table_count} {t(" tables · ")}{set.vnb_count} {t(" DSOs")}{set.undated_document_count ? t(" · {0} undated documents", set.undated_document_count) : ''}</small></div>
        <div className="settings-set-row-actions"><button type="button" onClick={() => edit(set)} disabled={busy} aria-label={t("Edit set {0}", set.name)}><Pencil size={13} /> {t(" Edit")}</button>
        <button type="button" onClick={() => void remove(set)} disabled={busy} aria-label={t("Delete set {0}", set.name)}><Trash2 size={13} /> {t(" Delete")}</button></div>
      </div>)}
    </div>
  </section>
}
