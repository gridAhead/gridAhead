// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { AppHeader } from './AppHeader'
import { useTableTypes, type TableType } from './tableTypes'

export function SettingsPage() {
  const { types, error: loadError, reload } = useTableTypes()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { document.title = t("NAP Tool · Settings") }, [])

  async function change(method: string, path: string, body?: object) {
    setBusy(true); setError('')
    try {
      const response = await fetch(path, {
        method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(result.detail || t("Could not save table types"))
      if (method === 'POST') setName('')
      reload()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not save table types")) }
    finally { setBusy(false) }
  }

  function remove(type: TableType) {
    if (window.confirm(t("Delete table type \"{0}\"?", type.name))) void change('DELETE', `/api/table-types/${type.id}`)
  }

  return <div className="app-shell">
    <AppHeader page="settings" />
    <main className="settings-page">
      <div className="settings-content">
        <div className="settings-content-kicker">{t("TABLE TYPES")}</div>
        {loadError && <p className="review-error" role="alert">{t(loadError)}</p>}
        <section className="settings-card" aria-label={t("Table types")}>
          <div className="settings-section-heading"><div><h2>{t("Table types ")}<span className="pane-count">{types.length}</span></h2><p>{t("Manage the types available for extracted tables.")}</p></div></div>
          <form className="settings-create" onSubmit={(event) => { event.preventDefault(); void change('POST', '/api/table-types', { name: name.trim() }) }}>
            <label htmlFor="type-name">{t("New table type")}</label>
            <input id="type-name" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} placeholder={t("Type name")} required disabled={busy} />
            <button className="settings-primary" type="submit" disabled={busy || !name.trim()}><Plus size={14} /> {t(" Add type")}</button>
          </form>
          {error && <p className="review-error" role="alert">{t(error)}</p>}
          <div className="settings-types">
            {types.map((type) => <div className="settings-type" key={type.id}>
              <div><strong>{type.name}</strong><small>{type.table_count} {t(" tables · ")}{type.set_count} {t(" sets")}</small></div>
              <button type="button" onClick={() => remove(type)} disabled={busy || type.table_count > 0 || type.set_count > 0} title={type.table_count || type.set_count ? t("This type is in use") : t("Delete type")} aria-label={t("Delete {0}", type.name)}><Trash2 size={13} /> {t(" Delete")}</button>
            </div>)}
          </div>
        </section>
      </div>
    </main>
  </div>
}
