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

export interface RemoteModel {
  model_id: string
  downloads: number
  likes: number
  files: Array<{ name: string; url: string }>
}

export interface DownloadJob {
  id: string
  target_path: string
  status: string
  downloaded_bytes: number
  total_bytes: number | null
  error: string | null
}

export interface Profile {
  id: string
  name: string
  mode: 'single' | 'router'
  model_path: string
  model_alias: string
  models_dir: string
  models_preset: string
  models_max: number
  models_autoload: boolean
  models: LaunchModel[]
  catalog_args: SelectedArgument[]
  custom_args_text: string
  labels: Record<string, string>
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

export interface BenchmarkAttemptDetail extends BenchmarkAttempt {
  job_id: string
  request: Record<string, unknown>
  response: unknown
  output_text: string
  resource: Record<string, unknown>
  created_at: string
}

export interface BenchmarkServiceUnit {
  unit_name: string
  unit_path: string
  content: string
  source: 'snapshot' | 'reconstructed' | 'current-service-fallback'
}

export interface MetricSummary {
  average: number | null
  median: number | null
  p10: number | null
  p90: number | null
  min: number | null
  max: number | null
}

export interface BenchmarkJob {
  id: string
  name: string
  service_id: string | null
  model_alias: string | null
  profile_id: string | null
  task_id: string | null
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

export interface BenchmarkTask {
  id: string
  name: string
  service_id: string
  model_alias: string
  config: Record<string, unknown>
  last_run_status: string | null
  run_count: number
  created_at: string
  updated_at: string
  recent_runs?: BenchmarkJob[]
}

export interface QueueItem {
  id: string
  task_id: string
  task_name: string
  run_name: string | null
  order_index: number
  status: string
  enqueued_at: string
  started_at: string | null
  last_run_id: string | null
  run?: {
    id: string
    status: string
    name: string
    error: string | null
    summary: Record<string, unknown>
  }
}

export interface TaskQueueState {
  id: number
  status: 'idle' | 'running' | 'paused' | 'stopping' | 'stopping_queue' | 'error'
  interval_ms: number
  cancel_timeout_ms: number
  current_item_id: string | null
  next_dispatch_at: string | null
  session_id: string | null
  items: QueueItem[]
  current_item: QueueItem | null
  session_stats: {
    successes: number
    failures: number
    canceled: number
  }
  scheduler?: {
    consecutive_failures: number
    last_error: string | null
    last_error_at: string | null
    failure_threshold: number
  }
}

export interface LaunchModel {
  id?: string
  alias: string
  model_path: string
  display_name: string
  enabled: boolean
}

export interface LaunchConfig {
  mode: 'single' | 'router'
  model_path: string
  model_alias: string
  models_dir: string
  models_preset: string
  models_max: number
  models_autoload: boolean
  models: LaunchModel[]
  catalog_args: SelectedArgument[]
  custom_args_text: string
  labels: Record<string, string>
}

export interface LlamaService {
  id: string
  name: string
  description: string
  unit_name: string
  unit_path: string
  server_bin: string
  service_user: string
  service_group: string
  working_directory: string
  host: string
  port: number
  health_path: string
  request_path: string
  service_type: string
  restart_policy: string
  restart_sec: number
  unit_extra_text: string
  service_extra_text: string
  install_extra_text: string
  rendered_unit: string
  source_profile_id: string | null
  applied_source_profile_id: string | null
  draft_launch_config: LaunchConfig | null
  applied_launch_config: LaunchConfig | null
  applied_service_config: Record<string, unknown> | null
  applied_model_aliases: string[]
  has_pending_changes: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
  status?: { ok: boolean; stdout: string; stderr: string }
}
