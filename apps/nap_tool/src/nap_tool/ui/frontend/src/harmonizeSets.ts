// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useState } from 'react'

export type SetCounts = { table_count: number; vnb_count: number; undated_document_count: number }
export type HarmonizeSet = SetCounts & {
  id: number; name: string; slug: string; table_type_id: number; is_grid_measure: boolean
  dso_ids: number[]; years: number[]; current_scheme_id: number | null; created_at: string
}
export type SetOptions = { vnbs: { id: number; name: string }[]; years: number[] }

export async function setsApi<T>(path = '', method = 'GET', body?: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/harmonize/sets${path}`, {
    method, signal, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : t("Could not load or save sets"))
  return result as T
}

export function useHarmonizeSets() {
  const [sets, setSets] = useState<HarmonizeSet[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setsApi<HarmonizeSet[]>('', 'GET', undefined, controller.signal)
      .then((items) => { setSets(items); setError('') })
      .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])
  return { sets, error, loading, reload: () => setRevision((value) => value + 1) }
}
