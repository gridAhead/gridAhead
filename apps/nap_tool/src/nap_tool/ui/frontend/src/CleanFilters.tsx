// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
export type CleanFilter = 'manual' | 'unresolved_modified' | 'unresolved'
export const cleanFilterLabels: Record<CleanFilter, string> = {
  manual: t("Manual edits"), unresolved_modified: t("Manual edits after unresolved values"), unresolved: t("Unresolved"),
}
export function CleanFilters({ value, onChange, label = t("Edit status") }: { value: CleanFilter | null; onChange: (value: CleanFilter | null) => void; label?: string }) {
  return <label className="filter-field clean-filter-field">
    <span className="filter-label">{label}</span>
    <span className="filter-select-wrap">
      <select aria-label={t("Filter by {0}", label)} value={value ?? ''} onChange={(event) => onChange(event.target.value ? event.target.value as CleanFilter : null)}>
        <option value="">{t("All ")}</option>
        {Object.entries(cleanFilterLabels).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
    </span>
  </label>
}
