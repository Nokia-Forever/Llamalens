export interface AppSettings {
  llama_server_bin: string
  llama_service_name: string
  llama_service_file: string
  service_scope: 'system' | 'user'
  service_control_command: string
  active_profile_path: string
  model_roots: string[]
  web_host: string
  web_port: number
  llama_host: string
  llama_port: number
  health_path: string
  request_path: string
  download_timeout_seconds: number
}

export interface CatalogArgument {
  id: number
  key: string
  aliases: string[]
  value_hint: string
  description: string
  category: string
  source: string
  supported: boolean
}

export interface SelectedArgument {
  flag: string
  value: string
}

export interface ModelFile {
  id: number
  path: string
  name: string
  size_bytes: number
  quantization: string | null
  modified_at: string | null
  available: boolean
}

export interface Profile {
  id: string
  name: string
  model_path: string
  catalog_args: SelectedArgument[]
  custom_args_text: string
  labels: Record<string, string>
  is_active: boolean
  final_argv: string[]
  warnings: string[]
  created_at: string
  updated_at: string
}

export interface BenchmarkAttempt {
  id: number
  ordinal: number
  warmup: boolean
  status: string
  measurement_mode: string
  ttft_ms: number | null
  prefill_tps: number | null
  decode_tps: number | null
  client_decode_tps: number | null
  total_ms: number | null
  prompt_tokens: number | null
  predicted_tokens: number | null
  error: string | null
}

export interface MetricSummary {
  median: number | null
  p10: number | null
  p90: number | null
  min: number | null
  max: number | null
}

export interface BenchmarkJob {
  id: string
  name: string
  profile_id: string | null
  status: string
  config: Record<string, unknown>
  summary: {
    successes?: number
    failures?: number
    metrics?: Record<string, MetricSummary>
  }
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  attempts?: BenchmarkAttempt[]
}
