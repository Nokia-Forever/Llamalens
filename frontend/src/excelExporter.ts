import ExcelJS from 'exceljs'
import type { BenchmarkJob } from './types'
import { formatDate } from './utils'
import { aggregateStat, getMetricStat, STAT_LABELS, targetName, type MetricConfig, type StatKey } from './metricsStats'

export interface ExportImageSource {
  title: string
  dataUrl: string
}

export interface ExportParams {
  jobs: BenchmarkJob[]
  metrics: MetricConfig[]
  includeAttempts: boolean
  images: ExportImageSource[]
}

const STAT_KEYS: StatKey[] = ['average', 'median', 'p10', 'p90', 'min', 'max']

const HEADER_FILL = {
  type: 'pattern',
  pattern: 'solid',
  fgColor: { argb: 'FFDFF2ED' },
} as ExcelJS.Fill
const HEADER_FONT = { bold: true, color: { argb: 'FF056653' } } as ExcelJS.Font
const ALIGN_CENTER = { vertical: 'middle', horizontal: 'center', wrapText: true } as ExcelJS.Alignment

function dataUrlToBase64(dataUrl: string): string {
  const idx = dataUrl.indexOf(',')
  return idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl
}

function stamp(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
}

export async function buildWorkbookBlob(params: ExportParams): Promise<Blob> {
  const { jobs, metrics, includeAttempts, images } = params
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'LlamaLens'
  workbook.created = new Date()

  const summarySheet = workbook.addWorksheet('汇总数据', { views: [{ state: 'frozen', ySplit: 1 }] })
  const baseHeaders = ['序号', '测试名', '目标', '模型', '状态', '创建时间', '成功数', '失败数']
  const statHeaders = metrics.flatMap((metric) => STAT_KEYS.map((stat) => `${metric.label} ${STAT_LABELS[stat]}`))
  const headers = [...baseHeaders, ...statHeaders]
  summarySheet.columns = [
    { key: 'idx', width: 6 },
    { key: 'name', width: 26 },
    { key: 'target', width: 34 },
    { key: 'model', width: 16 },
    { key: 'status', width: 10 },
    { key: 'created', width: 20 },
    { key: 'successes', width: 8 },
    { key: 'failures', width: 8 },
    ...statHeaders.map((title) => ({ key: title, width: 14 })),
  ]
  const headerRow = summarySheet.getRow(1)
  headers.forEach((value, index) => {
    const cell = headerRow.getCell(index + 1)
    cell.value = value
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = ALIGN_CENTER
    cell.border = { bottom: { style: 'thin', color: { argb: 'FFD6DDE0' } } }
  })
  headerRow.height = 20

  jobs.forEach((job, jobIndex) => {
    const values: (string | number)[] = [
      jobIndex + 1,
      job.name,
      targetName(job),
      job.model_alias || '',
      job.status,
      formatDate(job.created_at),
      job.summary.successes || 0,
      job.summary.failures || 0,
      ...metrics.flatMap((metric) => STAT_KEYS.map((stat) => getMetricStat(job, metric.key, stat) ?? '')),
    ]
    const row = summarySheet.addRow(values)
    values.forEach((value, index) => {
      if (index >= 8 && typeof value === 'number') {
        const cell = row.getCell(index + 1)
        cell.numFmt = '0.00'
      }
    })
  })

  const totalRow = summarySheet.addRow([
    '合计/平均', '', '', '', '', '', '', '',
    ...metrics.flatMap((metric) => STAT_KEYS.map((stat) => aggregateStat(jobs, metric.key, stat).average ?? '')),
  ])
  totalRow.eachCell((cell) => {
    cell.font = { bold: true }
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE5EAEC' } } as ExcelJS.Fill
  })

  const chartSheet = workbook.addWorksheet('图表')
  chartSheet.columns = [{ width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }, { width: 14 }]
  let cursor = 1
  if (images.length) {
    images.forEach((image) => {
      const titleCell = chartSheet.getCell(`A${cursor}`)
      titleCell.value = image.title
      titleCell.font = { bold: true, size: 13, color: { argb: 'FF056653' } }
      cursor += 1
      const imgStart = cursor
      const imgEnd = cursor + 21
      try {
        const imageId = workbook.addImage({ base64: dataUrlToBase64(image.dataUrl), extension: 'png' })
        chartSheet.addImage(imageId, `A${imgStart}:L${imgEnd}`)
      } catch (error) {
        const warn = chartSheet.getCell(`A${imgStart}`)
        warn.value = `图表嵌入失败: ${error instanceof Error ? error.message : String(error)}`
        warn.font = { color: { argb: 'FFBD3C3C' } }
      }
      cursor += 23
    })
  } else {
    chartSheet.getCell('A1').value = '没有可导出的图表，请在观测页启用至少一张图表。'
  }

  if (includeAttempts) {
    const attemptSheet = workbook.addWorksheet('轮次明细', { views: [{ state: 'frozen', ySplit: 1 }] })
    const attemptHeaders = ['测试名', '序号', '模式', 'TTFT ms', 'Prefill tok/s', 'Decode tok/s', 'Client Decode tok/s', 'Total ms', 'Prompt tokens', 'Predicted tokens', '状态']
    attemptSheet.columns = attemptHeaders.map((title, index) => ({ key: String(index), width: 16 }))
    const aHeaderRow = attemptSheet.getRow(1)
    attemptHeaders.forEach((value, index) => {
      const cell = aHeaderRow.getCell(index + 1)
      cell.value = value
      cell.font = HEADER_FONT
      cell.fill = HEADER_FILL
      cell.alignment = ALIGN_CENTER
    })
    jobs.forEach((job) => {
      const attempts = (job.attempts || []).filter((attempt) => !attempt.warmup && attempt.status === 'succeeded')
      attempts.forEach((attempt) => {
        attemptSheet.addRow([
          job.name,
          attempt.ordinal,
          attempt.measurement_mode,
          attempt.ttft_ms ?? '',
          attempt.prefill_tps ?? '',
          attempt.decode_tps ?? '',
          attempt.client_decode_tps ?? '',
          attempt.total_ms ?? '',
          attempt.prompt_tokens ?? '',
          attempt.predicted_tokens ?? '',
          attempt.status,
        ])
      })
    })
  }

  const buffer = await workbook.xlsx.writeBuffer()
  return new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
}

export function downloadBlob(blob: Blob, fileName: string = `llamalens-observation-${stamp()}.xlsx`): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.click()
  URL.revokeObjectURL(url)
}

export async function exportObservationExcel(params: ExportParams): Promise<void> {
  const blob = await buildWorkbookBlob(params)
  downloadBlob(blob)
}
