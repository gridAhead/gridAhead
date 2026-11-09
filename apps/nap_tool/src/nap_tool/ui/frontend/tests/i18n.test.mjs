// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'

for (const language of ['en', 'de']) {
  test(`UI messages in ${language} preserve inserted data`, async () => {
    globalThis.localStorage = { getItem: () => language }
    const { t, messages } = await import(`../src/i18n.ts?test=${language}`)
    assert.equal(t('Classification'), language === 'de' ? 'Klassifikation' : 'Classification')
    assert.equal(t('Table #{0} is unavailable', 42), language === 'de' ? 'Tabelle #42 ist nicht verfügbar' : 'Table #42 is unavailable')
    assert.equal(t('Table #42 is unavailable'), language === 'de' ? 'Tabelle #42 ist nicht verfügbar' : 'Table #42 is unavailable')
    assert.equal(t('Scheme name'), language === 'de' ? 'Schemaname' : 'Scheme name')
    const title = 'Grid measures <operator> {0}'
    assert.equal(t('Delete {0}', title), language === 'de' ? `${title} löschen` : `Delete ${title}`)
    assert.equal(t('Unregistered source value'), 'Unregistered source value')
    for (const [source, translated] of Object.entries(messages)) {
      assert.ok(!/\p{Script=Han}/u.test(source + translated), source)
      const placeholders = value => [...value.matchAll(/\{(\d+)\}/g)].map(match => match[1]).sort()
      assert.deepEqual(placeholders(translated), placeholders(source), source)
    }
  })
}

test('UI source contains no Chinese interface text', () => {
  const sourceDir = new URL('../src/', import.meta.url)
  for (const name of readdirSync(sourceDir)) {
    if (!/\.tsx?$/.test(name)) continue
    assert.ok(!/\p{Script=Han}/u.test(readFileSync(new URL(name, sourceDir), 'utf8')), name)
  }
})
