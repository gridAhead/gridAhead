// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect } from 'react'
import { AppHeader } from './AppHeader'
import { t } from './i18n'
import { SetsSettings } from './SetsSettings'
import { useTableTypes } from './tableTypes'

export function SetsPage() {
  const { types, error, reload } = useTableTypes()

  useEffect(() => { document.title = t("NAP Tool · Sets") }, [])

  return <div className="app-shell">
    <AppHeader page="sets" />
    <main className="settings-page">
      <div className="settings-content">
        <div className="settings-content-kicker">{t("HARMONIZATION")}</div>
        {error && <p className="review-error" role="alert">{t(error)}</p>}
        <SetsSettings types={types} onChanged={reload} />
      </div>
    </main>
  </div>
}
