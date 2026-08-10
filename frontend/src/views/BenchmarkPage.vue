<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { IconDeviceFloppy, IconPlaylistAdd } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import type { BenchmarkTask, LaunchModel, LlamaService } from '../types'

const store = useAppStore()
const route = useRoute()
const router = useRouter()
const services = ref<LlamaService[]>([])
const serviceId = ref('')
const modelAlias = ref('')
const extraText = ref('{}')
const stopText = ref('')
const seedText = ref('42')
const editingTaskId = ref<string | null>(null)
const saving = ref(false)

const form = reactive({
  name: `Benchmark ${new Date().toLocaleString()}`,
  prompt: '',
  max_tokens: 256,
  timeout_seconds: 300,
  temperature: 0,
  cache_prompt: false,
  warmup_runs: 1,
  repeat_runs: 3,
  repeat_delay_ms: 0,
  concurrency: 1,
})

const selectedService = computed(() => services.value.find((item) => item.id === serviceId.value) || null)
const serviceModels = computed<LaunchModel[]>(() => {
  const config = selectedService.value?.applied_launch_config
  if (!config) return []
  if (config.mode === 'single') {
    return [{ alias: config.model_alias, model_path: config.model_path, display_name: config.model_alias, enabled: true }]
  }
  return config.models.filter((item) => item.enabled)
})
const normalizedSeed = computed(() => String(seedText.value ?? '').trim())
const requestPreview = computed(() => ({
  ...safeExtra(false),
  prompt: form.prompt || '<请输入 Prompt>',
  n_predict: form.max_tokens,
  temperature: form.temperature,
  ...(normalizedSeed.value === '' ? {} : { seed: Number(normalizedSeed.value) }),
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

function buildPayload() {
  return {
    ...form,
    service_id: serviceId.value,
    model_alias: modelAlias.value,
    seed: normalizedSeed.value === '' ? null : Number(normalizedSeed.value),
    stop: stopText.value.split('\n').map((item) => item.trim()).filter(Boolean),
    extra_params: safeExtra(),
  }
}

async function loadServices() {
  services.value = await api<LlamaService[]>('/services')
  if (!serviceId.value) {
    const first = services.value.find((service) => service.applied_launch_config)
    if (first) {
      serviceId.value = first.id
      if (!modelAlias.value) modelAlias.value = first.applied_model_aliases[0] || ''
    }
  }
}

async function loadTask(taskId: string) {
  try {
    const task = await api<BenchmarkTask>(`/tasks/${taskId}`)
    editingTaskId.value = task.id
    form.name = task.name
    serviceId.value = task.service_id
    modelAlias.value = task.model_alias
    const config = task.config as Record<string, unknown>
    form.prompt = String(config.prompt || '')
    form.max_tokens = Number(config.max_tokens || 256)
    form.timeout_seconds = Number(config.timeout_seconds || 300)
    form.temperature = Number(config.temperature || 0)
    form.cache_prompt = Boolean(config.cache_prompt)
    form.warmup_runs = Number(config.warmup_runs || 1)
    form.repeat_runs = Number(config.repeat_runs || 3)
    form.repeat_delay_ms = Number(config.repeat_delay_ms || 0)
    form.concurrency = Number(config.concurrency || 1)
    if (config.seed != null) seedText.value = String(config.seed)
    else seedText.value = ''
    const stopArr = config.stop as string[] | undefined
    stopText.value = stopArr ? stopArr.join('\n') : ''
    extraText.value = config.extra_params ? JSON.stringify(config.extra_params, null, 2) : '{}'
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载任务失败')
  }
}

async function saveTask() {
  if (!form.prompt.trim()) return store.notify('error', '请输入测试 Prompt')
  if (!serviceId.value || !modelAlias.value) return store.notify('error', '请选择 Service 和模型 Alias')
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingTaskId.value) {
      await api(`/tasks/${editingTaskId.value}`, { method: 'PATCH', ...jsonBody(payload) })
      store.notify('success', '任务已更新')
    } else {
      await api('/tasks', { method: 'POST', ...jsonBody(payload) })
      store.notify('success', '任务已保存')
    }
    router.push('/tasks')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '保存任务失败')
  } finally {
    saving.value = false
  }
}

async function saveAndEnqueue() {
  if (!form.prompt.trim()) return store.notify('error', '请输入测试 Prompt')
  if (!serviceId.value || !modelAlias.value) return store.notify('error', '请选择 Service 和模型 Alias')
  saving.value = true
  try {
    const payload = buildPayload()
    let taskId: string
    if (editingTaskId.value) {
      const updated = await api<BenchmarkTask>(`/tasks/${editingTaskId.value}`, { method: 'PATCH', ...jsonBody(payload) })
      taskId = updated.id
      store.notify('success', '任务已更新并加入队列')
    } else {
      const created = await api<BenchmarkTask>('/tasks', { method: 'POST', ...jsonBody(payload) })
      taskId = created.id
      store.notify('success', '任务已保存并加入队列')
    }
    await api('/queue/items', { method: 'POST', ...jsonBody({ task_id: taskId, position: 'tail' }) })
    router.push('/tasks')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '保存并加入队列失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const taskQuery = route.query.task
  if (taskQuery && typeof taskQuery === 'string') {
    await loadTask(taskQuery)
  }
  await loadServices()
})
</script>

<template>
  <form class="page-stack" @submit.prevent="saveTask">
    <div v-if="selectedService && !selectedService.applied_launch_config" class="risk-banner neutral">
      这个 Service 尚未成功部署，没有 applied 启动快照，因此不能运行 Benchmark。
    </div>
    <div v-else-if="!services.some((service) => service.applied_launch_config)" class="risk-banner neutral">
      目前没有可测试的 Service。请先在 Services 页面导入 Profile 并成功部署。
    </div>

    <PageSection :title="editingTaskId ? '编辑任务' : '新建任务'" description="保存为任务后不会立即执行。前往「任务」页面加入队列并开始执行。">
      <div class="form-grid two-columns">
        <label class="field"><span>目标 Service</span><select v-model="serviceId" required @change="modelAlias = serviceModels[0]?.alias || ''"><option value="" disabled>选择 Service</option><option v-for="service in services" :key="service.id" :value="service.id" :disabled="!service.applied_launch_config">{{ service.name }} · {{ service.host }}:{{ service.port }}{{ service.applied_launch_config ? '' : '（未部署）' }}</option></select></label>
        <label class="field"><span>模型 Alias</span><select v-model="modelAlias" required><option value="" disabled>选择模型</option><option v-for="model in serviceModels" :key="model.alias" :value="model.alias">{{ model.display_name || model.alias }}</option></select></label>
        <label class="field"><span>任务名称</span><input v-model="form.name" required /></label>
        <label class="field"><span>已应用启动配置</span><input :value="selectedService?.applied_launch_config ? `${selectedService.applied_launch_config.mode} · ${selectedService.applied_model_aliases.join(', ')}` : '无 applied 快照'" disabled /></label>
      </div>
      <label class="field"><span>Prompt</span><textarea v-model="form.prompt" class="prompt-input" required placeholder="输入要测试的完整 Prompt" /></label>
    </PageSection>

    <PageSection title="生成与采样参数">
      <div class="form-grid four-columns">
        <label class="field"><span>Max tokens</span><input v-model.number="form.max_tokens" type="number" min="1" /></label>
        <label class="field"><span>Timeout 秒</span><input v-model.number="form.timeout_seconds" type="number" min="1" /></label>
        <label class="field"><span>Temperature</span><input v-model.number="form.temperature" type="number" min="0" step="0.1" /></label>
        <label class="field"><span>Seed</span><input v-model="seedText" type="number" /><small>固定随机种子有助于复现输出；留空表示不发送。</small></label>
        <label class="field"><span>Warm-up 次数</span><input v-model.number="form.warmup_runs" type="number" min="0" /><small>正式统计前预热，不计入 median、p10、p90。</small></label>
        <label class="field"><span>正式重复次数</span><input v-model.number="form.repeat_runs" type="number" min="1" /></label>
        <label class="field"><span>重复间隔 ms</span><input v-model.number="form.repeat_delay_ms" type="number" min="0" max="600000" /><small>只在正式轮次之间等待，最后一轮后不等待。</small></label>
        <label class="field"><span>并发数</span><input v-model.number="form.concurrency" type="number" min="1" /></label>
        <label class="check-field parameter-check"><input v-model="form.cache_prompt" type="checkbox" /><span>允许 Prompt cache<small>开启会复用相同 Prompt 的缓存，更接近缓存命中性能。</small></span></label>
      </div>
      <div class="form-grid two-columns">
        <label class="field"><span>Stop，每行一个</span><textarea v-model="stopText" rows="4" /><small>生成内容遇到任意停止字符串时提前结束。</small></label>
        <label class="field"><span>额外请求参数 JSON</span><textarea v-model="extraText" rows="4" spellcheck="false" /></label>
      </div>
    </PageSection>

    <PageSection title="最终请求预览" description="后端内部强制使用 SSE 测 TTFT，前端不显示流式 token。">
      <pre class="code-block compact-code">{{ JSON.stringify(requestPreview, null, 2) }}</pre>
    </PageSection>

    <div class="sticky-actions">
      <button type="button" class="button secondary" :disabled="saving" @click="saveAndEnqueue"><IconPlaylistAdd :size="17" />保存并加入队列</button>
      <button class="button primary" :disabled="saving || !selectedService?.applied_launch_config || !modelAlias"><IconDeviceFloppy :size="17" />{{ editingTaskId ? '更新任务' : '保存任务' }}</button>
    </div>
  </form>
</template>
