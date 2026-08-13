<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { IconDeviceFloppy, IconPlaylistAdd } from '@tabler/icons-vue'
import { tasksApi, servicesApi, queueApi } from '../api'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import { useBusy } from '../composables/useBusy'
import type { LaunchModel, LlamaService } from '../types'

const { t } = useI18n()
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
const { run: runBusy, isBusy } = useBusy()

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
  prompt: form.prompt || t('benchmarks.promptPlaceholderPreview'),
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
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(t('benchmarks.extraParamsMustBeObject'))
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
  services.value = await servicesApi.list()
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
    const task = await tasksApi.get(taskId)
    editingTaskId.value = task.id
    form.name = task.name
    serviceId.value = task.service_id
    modelAlias.value = task.model_alias
    const config = task.config as Record<string, unknown>
    form.prompt = String(config.prompt ?? '')
    form.max_tokens = Number(config.max_tokens ?? 256)
    form.timeout_seconds = Number(config.timeout_seconds ?? 300)
    form.temperature = Number(config.temperature ?? 0)
    form.cache_prompt = Boolean(config.cache_prompt)
    form.warmup_runs = Number(config.warmup_runs ?? 1)
    form.repeat_runs = Number(config.repeat_runs ?? 3)
    form.repeat_delay_ms = Number(config.repeat_delay_ms ?? 0)
    form.concurrency = Number(config.concurrency ?? 1)
    if (config.seed != null) seedText.value = String(config.seed)
    else seedText.value = ''
    const stopArr = config.stop as string[] | undefined
    stopText.value = stopArr ? stopArr.join('\n') : ''
    extraText.value = config.extra_params ? JSON.stringify(config.extra_params, null, 2) : '{}'
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('benchmarks.loadTaskFailed'))
  }
}

async function saveTask() {
  if (!form.prompt.trim()) return store.notify('error', t('benchmarks.promptRequired'))
  if (!serviceId.value || !modelAlias.value) return store.notify('error', t('benchmarks.serviceAndAliasRequired'))
  await runBusy('benchmark.save', async () => {
    try {
      const payload = buildPayload()
      if (editingTaskId.value) {
        await tasksApi.update(editingTaskId.value, payload)
        store.notify('success', t('benchmarks.taskUpdated'))
      } else {
        await tasksApi.create(payload)
        store.notify('success', t('benchmarks.taskSaved'))
      }
      router.push('/tasks')
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('benchmarks.saveFailed'))
    }
  })
}

async function saveAndEnqueue() {
  if (!form.prompt.trim()) return store.notify('error', t('benchmarks.promptRequired'))
  if (!serviceId.value || !modelAlias.value) return store.notify('error', t('benchmarks.serviceAndAliasRequired'))
  await runBusy('benchmark.save', async () => {
    try {
      const payload = buildPayload()
      let taskId: string
      if (editingTaskId.value) {
        const updated = await tasksApi.update(editingTaskId.value, payload)
        taskId = updated.id
        store.notify('success', t('benchmarks.taskUpdatedEnqueued'))
      } else {
        const created = await tasksApi.create(payload)
        taskId = created.id
        store.notify('success', t('benchmarks.taskSavedEnqueued'))
      }
      await queueApi.enqueue({ task_id: taskId, position: 'tail' })
      router.push('/tasks')
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('benchmarks.saveEnqueueFailed'))
    }
  })
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
      {{ t('benchmarks.serviceNotDeployed') }}
    </div>
    <div v-else-if="!services.some((service) => service.applied_launch_config)" class="risk-banner neutral">
      {{ t('benchmarks.noTestableService') }}
    </div>

    <PageSection :title="editingTaskId ? t('benchmarks.editTask') : t('benchmarks.newTask')" :description="t('benchmarks.taskDesc')">
      <div class="form-grid two-columns">
        <label class="field"><span>{{ t('benchmarks.service') }}</span><select v-model="serviceId" required @change="modelAlias = serviceModels[0]?.alias || ''"><option value="" disabled>{{ t('benchmarks.selectService') }}</option><option v-for="service in services" :key="service.id" :value="service.id" :disabled="!service.applied_launch_config">{{ service.name }} · {{ service.host }}:{{ service.port }}{{ service.applied_launch_config ? '' : t('benchmarks.notDeployed') }}</option></select></label>
        <label class="field"><span>{{ t('benchmarks.modelAlias') }}</span><select v-model="modelAlias" required><option value="" disabled>{{ t('benchmarks.selectModel') }}</option><option v-for="model in serviceModels" :key="model.alias" :value="model.alias">{{ model.display_name || model.alias }}</option></select></label>
        <label class="field"><span>{{ t('benchmarks.taskName') }}</span><input v-model="form.name" required /></label>
        <label class="field"><span>{{ t('benchmarks.appliedLaunchConfig') }}</span><input :value="selectedService?.applied_launch_config ? `${selectedService.applied_launch_config.mode} · ${selectedService.applied_model_aliases.join(', ')}` : t('benchmarks.noAppliedSnapshot')" disabled /></label>
      </div>
      <label class="field"><span>Prompt</span><textarea v-model="form.prompt" class="prompt-input" required :placeholder="t('benchmarks.promptPlaceholder')" /></label>
    </PageSection>

    <PageSection :title="t('benchmarks.generationParams')">
      <div class="form-grid four-columns">
        <label class="field"><span>Max tokens</span><input v-model.number="form.max_tokens" type="number" min="1" /></label>
        <label class="field"><span>{{ t('benchmarks.timeoutSeconds') }}</span><input v-model.number="form.timeout_seconds" type="number" min="1" /></label>
        <label class="field"><span>Temperature</span><input v-model.number="form.temperature" type="number" min="0" step="0.1" /></label>
        <label class="field"><span>Seed</span><input v-model="seedText" type="number" /><small>{{ t('benchmarks.seedHint') }}</small></label>
        <label class="field"><span>{{ t('benchmarks.warmupRuns') }}</span><input v-model.number="form.warmup_runs" type="number" min="0" /><small>{{ t('benchmarks.warmupRunsHint') }}</small></label>
        <label class="field"><span>{{ t('benchmarks.repeatRuns') }}</span><input v-model.number="form.repeat_runs" type="number" min="1" /></label>
        <label class="field"><span>{{ t('benchmarks.repeatDelayMs') }}</span><input v-model.number="form.repeat_delay_ms" type="number" min="0" max="600000" /><small>{{ t('benchmarks.repeatDelayMsHint') }}</small></label>
        <label class="field"><span>{{ t('benchmarks.concurrency') }}</span><input v-model.number="form.concurrency" type="number" min="1" /></label>
        <label class="check-field parameter-check"><input v-model="form.cache_prompt" type="checkbox" /><span>{{ t('benchmarks.cachePrompt') }}<small>{{ t('benchmarks.cachePromptHint') }}</small></span></label>
      </div>
      <div class="form-grid two-columns">
        <label class="field"><span>{{ t('benchmarks.stopPerLine') }}</span><textarea v-model="stopText" rows="4" /><small>{{ t('benchmarks.stopHint') }}</small></label>
        <label class="field"><span>{{ t('benchmarks.extraParamsJson') }}</span><textarea v-model="extraText" rows="4" spellcheck="false" /></label>
      </div>
    </PageSection>

    <PageSection :title="t('benchmarks.requestPreview')" :description="t('benchmarks.requestPreviewDesc')">
      <pre class="code-block compact-code">{{ JSON.stringify(requestPreview, null, 2) }}</pre>
    </PageSection>

    <div class="sticky-actions">
      <button type="button" class="button secondary" :disabled="isBusy('benchmark.save')" @click="saveAndEnqueue"><IconPlaylistAdd :size="17" />{{ t('benchmarks.saveAndEnqueue') }}</button>
      <button class="button primary" :disabled="isBusy('benchmark.save') || !selectedService?.applied_launch_config || !modelAlias"><IconDeviceFloppy :size="17" />{{ editingTaskId ? t('benchmarks.updateTask') : t('benchmarks.saveTask') }}</button>
    </div>
  </form>
</template>
