<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { IconPlayerPlay, IconPlayerStop, IconRefresh } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import MetricBlock from '../components/MetricBlock.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { BenchmarkJob, LlamaService, Profile } from '../types'

const store = useAppStore()
const profiles = ref<Profile[]>([])
const services = ref<LlamaService[]>([])
const serviceId = ref('')
const modelAlias = ref('')
const current = ref<BenchmarkJob | null>(null)
const running = ref(false)
const extraText = ref('{}')
const stopText = ref('')
const seedText = ref('42')
let timer: number | undefined

const form = reactive({
  name: `Benchmark ${new Date().toLocaleString()}`,
  prompt: '',
  max_tokens: 256,
  timeout_seconds: 300,
  temperature: 0,
  cache_prompt: false,
  warmup_runs: 1,
  repeat_runs: 3,
  concurrency: 1,
})

const selectedService = computed(() => services.value.find((item) => item.id === serviceId.value) || null)
const serviceModels = computed(() => selectedService.value?.models.filter((item) => item.enabled) || [])
const activeProfile = computed(() => profiles.value.find((item) => item.is_active && item.service_id === serviceId.value) || null)
const metrics = computed(() => current.value?.summary.metrics || {})
const requestPreview = computed(() => ({
  ...safeExtra(false),
  prompt: form.prompt || '<请输入 Prompt>',
  n_predict: form.max_tokens,
  temperature: form.temperature,
  ...(seedText.value.trim() === '' ? {} : { seed: Number(seedText.value) }),
  stop: stopText.value.split('\n').map((item) => item.trim()).filter(Boolean),
  cache_prompt: form.cache_prompt,
  model: modelAlias.value || '<model-alias>',
  stream: true,
}))

function safeExtra(throwOnError = true): Record<string, unknown> {
  try {
    const value = JSON.parse(extraText.value || '{}')
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('额外参数必须是 JSON 对象')
    return value
  } catch (error) {
    if (throwOnError) throw error
    return { '<invalid-json>': extraText.value }
  }
}

async function loadProfiles() {
  ;[profiles.value, services.value] = await Promise.all([api<Profile[]>('/profiles'), api<LlamaService[]>('/services')])
  if (!serviceId.value && services.value.length) {
    serviceId.value = services.value[0].id
    modelAlias.value = services.value[0].models.find((item) => item.enabled)?.alias || ''
  }
}

async function poll() {
  if (!current.value) return
  current.value = await api<BenchmarkJob>(`/benchmarks/${current.value.id}`)
  if (!['queued', 'running'].includes(current.value.status)) {
    running.value = false
    if (timer) window.clearInterval(timer)
    timer = undefined
  }
}

async function run() {
  if (!form.prompt.trim()) return store.notify('error', '请输入测试 Prompt')
  if (!serviceId.value || !modelAlias.value) return store.notify('error', '请选择 Service 和模型 Alias')
  running.value = true
  try {
    current.value = await api<BenchmarkJob>('/benchmarks', {
      method: 'POST',
      ...jsonBody({
        ...form,
        service_id: serviceId.value,
        model_alias: modelAlias.value,
        seed: seedText.value.trim() === '' ? null : Number(seedText.value),
        profile_id: activeProfile.value?.id || null,
        stop: stopText.value.split('\n').map((item) => item.trim()).filter(Boolean),
        extra_params: safeExtra(),
      }),
    })
    store.notify('success', 'Benchmark 已加入队列')
    timer = window.setInterval(() => poll().catch((error) => store.notify('error', error.message)), 1000)
    await poll()
  } catch (error) {
    running.value = false
    store.notify('error', error instanceof Error ? error.message : '创建 Benchmark 失败')
  }
}

async function cancel() {
  if (!current.value) return
  await api(`/benchmarks/${current.value.id}/cancel`, { method: 'POST' })
  store.notify('info', '已请求取消，正在执行的 HTTP 请求可能需要等待返回或超时')
}

function format(value: number | null | undefined, digits = 2) {
  return value == null ? 'N/A' : value.toFixed(digits)
}

onMounted(loadProfiles)
onBeforeUnmount(() => timer && window.clearInterval(timer))
</script>

<template>
  <div class="benchmark-layout">
    <form class="page-stack" @submit.prevent="run">
      <div v-if="!activeProfile" class="risk-banner neutral">
        当前没有由 LlamaLens 激活的 Profile。测试仍可请求现有 llama-server，但结果不会关联配置快照。
      </div>

      <PageSection title="测试请求" description="Benchmark 参数不会写入 systemd service，也不会触发模型重启。">
        <div class="form-grid two-columns">
          <label class="field"><span>目标 Service</span><select v-model="serviceId" required @change="modelAlias = serviceModels[0]?.alias || ''"><option value="" disabled>选择 Service</option><option v-for="service in services" :key="service.id" :value="service.id">{{ service.name }} · {{ service.host }}:{{ service.port }}</option></select></label>
          <label class="field"><span>模型 Alias</span><select v-model="modelAlias" required><option value="" disabled>选择模型</option><option v-for="model in serviceModels" :key="model.alias" :value="model.alias">{{ model.display_name || model.alias }}</option></select></label>
          <label class="field"><span>测试名称</span><input v-model="form.name" required /></label>
          <label class="field"><span>当前 Profile</span><input :value="activeProfile?.name || '未关联'" disabled /></label>
        </div>
        <label class="field"><span>Prompt</span><textarea v-model="form.prompt" class="prompt-input" required placeholder="输入要测试的完整 Prompt" /></label>
      </PageSection>

      <PageSection title="生成与采样参数">
        <div class="form-grid four-columns">
          <label class="field"><span>Max tokens</span><input v-model.number="form.max_tokens" type="number" min="1" /></label>
          <label class="field"><span>Timeout 秒</span><input v-model.number="form.timeout_seconds" type="number" min="1" /></label>
          <label class="field"><span>Temperature</span><input v-model.number="form.temperature" type="number" min="0" step="0.1" /></label>
          <label class="field"><span>Seed</span><input v-model="seedText" type="number" /><small>留空表示不发送 seed。</small></label>
          <label class="field"><span>Warm-up 次数</span><input v-model.number="form.warmup_runs" type="number" min="0" /></label>
          <label class="field"><span>正式重复次数</span><input v-model.number="form.repeat_runs" type="number" min="1" /></label>
          <label class="field"><span>并发数</span><input v-model.number="form.concurrency" type="number" min="1" /></label>
          <label class="check-field"><input v-model="form.cache_prompt" type="checkbox" /><span>允许 Prompt cache</span></label>
        </div>
        <div class="form-grid two-columns">
          <label class="field"><span>Stop，每行一个</span><textarea v-model="stopText" rows="4" /></label>
          <label class="field"><span>额外请求参数 JSON</span><textarea v-model="extraText" rows="4" spellcheck="false" /></label>
        </div>
      </PageSection>

      <PageSection title="最终请求预览" description="后端内部强制使用 SSE 测 TTFT，前端不显示流式 token。">
        <pre class="code-block compact-code">{{ JSON.stringify(requestPreview, null, 2) }}</pre>
      </PageSection>

      <div class="sticky-actions">
        <button type="button" class="button secondary" :disabled="!current || !running" @click="cancel"><IconPlayerStop :size="17" />取消</button>
        <button class="button primary" :disabled="running"><IconPlayerPlay :size="17" />开始测试</button>
      </div>
    </form>

    <aside class="benchmark-monitor">
      <div class="monitor-heading">
        <div><strong>实时任务</strong><span>{{ current?.id?.slice(0, 8) || '尚未开始' }}</span></div>
        <button class="icon-button" :disabled="!current" aria-label="刷新任务" @click="poll"><IconRefresh :size="17" /></button>
      </div>
      <StatusBadge :status="current?.status || 'idle'" />
      <div class="monitor-metrics">
        <MetricBlock label="TTFT median" :value="`${format(metrics.ttft_ms?.median)} ms`" accent />
        <MetricBlock label="Prefill median" :value="`${format(metrics.prefill_tps?.median)} tok/s`" />
        <MetricBlock label="Decode median" :value="`${format(metrics.decode_tps?.median)} tok/s`" />
        <MetricBlock label="Client decode" :value="`${format(metrics.client_decode_tps?.median)} tok/s`" />
      </div>
      <div v-if="current" class="job-facts">
        <span>成功 <strong>{{ current.summary.successes || 0 }}</strong></span>
        <span>失败 <strong>{{ current.summary.failures || 0 }}</strong></span>
        <span>计划请求 <strong>{{ form.repeat_runs * form.concurrency }}</strong></span>
      </div>
      <p v-if="current?.error" class="error-text">{{ current.error }}</p>
      <div v-if="current?.attempts?.length" class="attempt-list">
        <div v-for="attempt in current.attempts" :key="attempt.id" class="attempt-row">
          <span>#{{ attempt.ordinal }} <small>{{ attempt.warmup ? 'warm-up' : attempt.measurement_mode }}</small></span>
          <strong>{{ format(attempt.decode_tps) }} tok/s</strong>
          <StatusBadge :status="attempt.status" />
        </div>
      </div>
      <div v-else class="empty-state compact">运行后会在这里显示每次测量。</div>
    </aside>
  </div>
</template>
