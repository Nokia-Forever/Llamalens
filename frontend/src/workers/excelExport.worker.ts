import { buildWorkbookBlob, type ExportParams } from '../excelExporter'

self.onmessage = async (e: MessageEvent) => {
  try {
    const blob = await buildWorkbookBlob(e.data as ExportParams)
    ;(self as unknown as { postMessage: (msg: unknown) => void }).postMessage({ ok: true, blob })
  } catch (err) {
    ;(self as unknown as { postMessage: (msg: unknown) => void }).postMessage({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    })
  }
}
