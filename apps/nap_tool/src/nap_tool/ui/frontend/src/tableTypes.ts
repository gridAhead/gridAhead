// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useState } from 'react'

export type TableType = { id: number; name: string; table_count: number; set_count: number }

export function useTableTypes() {
  const [types, setTypes] = useState<TableType[]>([])
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/table-types', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(t("Failed to load table types"))
        return response.json() as Promise<TableType[]>
      })
      .then((items) => { setTypes(items); setError('') })
      .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)) })
    return () => controller.abort()
  }, [revision])
  return { types, error, reload: () => setRevision((value) => value + 1) }
}
