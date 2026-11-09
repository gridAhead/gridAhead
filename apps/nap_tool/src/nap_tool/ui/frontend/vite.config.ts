// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite'

export default defineConfig({
  base: '/ui/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
