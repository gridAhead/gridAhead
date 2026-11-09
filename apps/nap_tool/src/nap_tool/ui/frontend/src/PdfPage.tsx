// SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
// SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
//
// SPDX-License-Identifier: Apache-2.0

import { t } from './i18n'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
// @ts-expect-error Vendored PDF.js browser build has no TypeScript declarations.
import { getDocument, GlobalWorkerOptions } from './vendor/pdfjs/pdf.min.mjs'

GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).toString()

type PdfRegion = { page: number; bbox: number[] | null }
type PdfPageProps = { extractId: number; page: number; zoom: number; regions: PdfRegion[] }
type Highlight = { left: number; top: number; width: number; height: number }

export function PdfPage({ extractId, page, zoom, regions }: PdfPageProps) {
  const viewerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number } | null>(null)
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [document, setDocument] = useState<{
    numPages: number
    getPage: (number: number) => Promise<{
      getViewport: (options: { scale: number }) => { width: number; height: number }
      render: (options: { canvas: HTMLCanvasElement; canvasContext: CanvasRenderingContext2D; viewport: { width: number; height: number } }) => { promise: Promise<void>; cancel: () => void }
    }>
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setDocument(null)
    setError(null)
    const task = getDocument({ url: `/api/extract-review/${extractId}/pdf` })
    task.promise.then((pdf: typeof document) => {
      if (active) setDocument(pdf)
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : t("Failed to load PDF"))
    })
    return () => { active = false; void task.destroy() }
  }, [extractId])

  useEffect(() => {
    if (!document || !canvasRef.current) return
    let active = true
    let renderTask: { promise: Promise<void>; cancel: () => void } | null = null
    setError(null)
    setDisplaySize(null)
    setHighlights([])
    document.getPage(page).then(async (pdfPage) => {
      if (!active || !canvasRef.current) return
      const canvas = canvasRef.current
      const baseViewport = pdfPage.getViewport({ scale: 1 })
      const displayWidth = Math.max(320, (viewerRef.current?.clientWidth ?? 900) - 24) * zoom
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      const viewport = pdfPage.getViewport({ scale: displayWidth * pixelRatio / baseViewport.width })
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${displayWidth}px`
      canvas.style.height = `${viewport.height / pixelRatio}px`
      const context = canvas.getContext('2d')
      if (!context) throw new Error(t("Could not create PDF canvas"))
      renderTask = pdfPage.render({ canvas, canvasContext: context, viewport })
      await renderTask.promise
      if (!active) return
      const scale = displayWidth / baseViewport.width
      const boxes = regions.flatMap((region) => {
        const bbox = region.bbox
        if (region.page !== page || !bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) return []
        const left = Math.max(0, Math.min(bbox[0], bbox[2]))
        const top = Math.max(0, Math.min(bbox[1], bbox[3]))
        const right = Math.min(baseViewport.width, Math.max(bbox[0], bbox[2]))
        const bottom = Math.min(baseViewport.height, Math.max(bbox[1], bbox[3]))
        if (right <= left || bottom <= top) return []
        return [{ left: left * scale, top: top * scale, width: (right - left) * scale, height: (bottom - top) * scale }]
      })
      setDisplaySize({ width: displayWidth, height: viewport.height / pixelRatio })
      setHighlights(boxes)
    }).catch((reason: unknown) => {
      if (active && !(reason instanceof Error && reason.name === 'RenderingCancelledException')) {
        setError(reason instanceof Error ? reason.message : t("Failed to render PDF page"))
      }
    })
    return () => { active = false; renderTask?.cancel() }
  }, [document, page, zoom, regions])

  useLayoutEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || !displaySize) return
    const first = highlights[0]
    viewer.scrollTop = first ? Math.max(0, first.top + 12 - viewer.clientHeight * 0.18) : 0
    viewer.scrollLeft = first ? Math.max(0, first.left + first.width / 2 + 12 - viewer.clientWidth / 2) : 0
  }, [displaySize, highlights])

  return <div className="review-pdf-viewer" ref={viewerRef}>
    {error ? <div className="review-empty-pdf">{t(error)}</div> : !document && <div className="review-pdf-loading">{t("Rendering PDF…")}</div>}
    <div className="review-pdf-page" style={displaySize ? { width: displaySize.width, height: displaySize.height } : undefined}>
      <canvas ref={canvasRef} aria-label={t("PDF page {0}", page)} style={{ display: document ? 'block' : 'none' }} />
      {highlights.map((box, index) => <div className="review-pdf-highlight" key={index} style={box} aria-hidden="true" />)}
    </div>
  </div>
}
