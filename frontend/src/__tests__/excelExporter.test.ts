import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { BenchmarkJob } from '../types'
import type { MetricConfig } from '../metricsStats'

const excelState = vi.hoisted(() => ({
  sheets: [] as Array<{ name: string; rows: unknown[][]; cells: Record<string, unknown> }>,
  writeBufferCalls: 0,
}))

vi.mock('exceljs', () => {
  const makeSheet = (name: string) => {
    const rows: unknown[][] = []
    const cells: Record<string, unknown> = {}
    return {
      name,
      rows,
      cells,
      columns: [] as unknown[],
      getRow: () => ({
        height: undefined,
        getCell: (col: number) => (cells[`r-${rows.length}-c-${col}`] = { value: undefined, font: undefined, fill: undefined, alignment: undefined, border: undefined }),
        eachCell: () => {},
      }),
      getCell: (ref: string) => (cells[ref] = cells[ref] || { value: undefined, font: undefined }),
      addRow: (values: unknown) => { rows.push(values as unknown[]); return { getCell: () => ({ numFmt: undefined }), eachCell: () => {} } },
      addImage: () => 'img-id',
    }
  }
  return {
    default: {
      Workbook: function (this: any) {
        this.creator = ''
        this.created = undefined
        this.addWorksheet = (name: string) => {
          const sheet = makeSheet(name)
          excelState.sheets.push(sheet)
          return sheet
        }
        this.addImage = () => 'img-id'
        this.xlsx = {
          writeBuffer: () => {
            excelState.writeBufferCalls++
            return Promise.resolve(new ArrayBuffer(8))
          },
        }
      },
    },
  }
})

import { exportObservationExcel } from '../excelExporter'

function makeJob(overrides: Partial<BenchmarkJob> = {}): BenchmarkJob {
  return {
    id: 'job-1', name: '测试任务', service_id: 'svc', model_alias: 'llama-7b', profile_id: null, task_id: null,
    status: 'succeeded', config: { service_snapshot: { name: 'svc-prod' } },
    summary: { successes: 1, failures: 0, metrics: { ttft_ms: { average: 100, median: 100, p10: 100, p90: 100, min: 100, max: 100 } } },
    error: null, created_at: '2024-01-01T00:00:00Z', started_at: null, finished_at: null,
    attempts: [{ id: 1, ordinal: 1, warmup: false, status: 'succeeded', measurement_mode: 'batch', ttft_ms: 100, prefill_tps: 50, decode_tps: 30, client_decode_tps: 28, total_ms: 200, prompt_tokens: 10, predicted_tokens: 20, error: null }],
    ...overrides,
  }
}

const ttftMetric: MetricConfig = { key: 'ttft_ms', label: 'TTFT', unit: 'ms', axis: 'right', lowerIsBetter: true }

describe('exportObservationExcel', () => {
  let capturedLink: { href: string; download: string; click: ReturnType<typeof vi.fn> }
  let origCreateObjectURL: typeof URL.createObjectURL | undefined
  let origRevokeObjectURL: typeof URL.revokeObjectURL | undefined

  beforeEach(() => {
    excelState.sheets.length = 0
    excelState.writeBufferCalls = 0
    capturedLink = { href: '', download: '', click: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') return capturedLink as unknown as HTMLElement
      return {} as HTMLElement
    })
    origCreateObjectURL = URL.createObjectURL
    origRevokeObjectURL = URL.revokeObjectURL
    ;(URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:fake-url'
    ;(URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {}
  })

  afterEach(() => {
    vi.restoreAllMocks()
    if (origCreateObjectURL !== undefined) {
      ;(URL as unknown as { createObjectURL: typeof URL.createObjectURL }).createObjectURL = origCreateObjectURL
    }
    if (origRevokeObjectURL !== undefined) {
      ;(URL as unknown as { revokeObjectURL: typeof URL.revokeObjectURL }).revokeObjectURL = origRevokeObjectURL
    }
  })

  it('includeAttempts=true 时创建汇总/图表/轮次明细三个工作表', async () => {
    await exportObservationExcel({ jobs: [makeJob()], metrics: [ttftMetric], includeAttempts: true, images: [] })
    expect(excelState.sheets.map((s) => s.name)).toEqual(['汇总数据', '图表', '轮次明细'])
    expect(excelState.writeBufferCalls).toBe(1)
  })

  it('includeAttempts=false 时只创建汇总和图表两个工作表', async () => {
    await exportObservationExcel({ jobs: [makeJob()], metrics: [ttftMetric], includeAttempts: false, images: [] })
    expect(excelState.sheets.map((s) => s.name)).toEqual(['汇总数据', '图表'])
  })

  it('汇总表每个 job 一行数据加合计行', async () => {
    await exportObservationExcel({
      jobs: [makeJob(), makeJob({ id: 'job-2', name: '任务2' })],
      metrics: [ttftMetric],
      includeAttempts: false,
      images: [],
    })
    const summary = excelState.sheets.find((s) => s.name === '汇总数据')!
    expect(summary.rows.length).toBe(3)
  })

  it('触发浏览器下载并生成带前缀的文件名', async () => {
    await exportObservationExcel({ jobs: [makeJob()], metrics: [ttftMetric], includeAttempts: false, images: [] })
    expect(capturedLink.click).toHaveBeenCalledTimes(1)
    expect(capturedLink.download).toContain('llamalens-observation-')
    expect(capturedLink.download).toMatch(/\.xlsx$/)
  })

  it('无图片时图表表写入空提示', async () => {
    await exportObservationExcel({ jobs: [makeJob()], metrics: [ttftMetric], includeAttempts: false, images: [] })
    const chart = excelState.sheets.find((s) => s.name === '图表')!
    expect((chart.cells['A1'] as { value: string }).value).toContain('没有可导出')
  })
})
