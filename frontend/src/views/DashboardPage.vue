<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { IconPlayerPlay, IconRefresh, IconServer } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import MetricBlock from '../components/MetricBlock.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { BenchmarkJob, LlamaService } from '../types'

const store = useAppStore()
const services = ref<LlamaService[]>([])
const benchmarks = ref<BenchmarkJob[]>([])
const loading = ref(true)
const actingId = ref<string | null>(null)
const healthyCount = computed(() => services.value.filter((item) => item.status?.ok).length)
const modelCount = computed(() => services.value.reduce((total, item) => total + item.models.filter((model) => model.enabled).length, 0))

async function load() {
  loading.value = true
  try {
    ;[services.value, benchmarks.value] = await Promise.all([
      api<LlamaService[]>('/services?with_status=true'), api<BenchmarkJob[]>('/benchmarks'),
    ])
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '加载概览失败') }
  finally { loading.value = false }
}

async function action(service: LlamaService, value: 'start' | 'restart') {
  actingId.value = service.id
  try {
    const result = await api<{ ok: boolean; stderr: string }>(`/services/${service.id}/action`, { method: 'POST', ...jsonBody({ action: value }) })
    store.notify(result.ok ? 'success' : 'error', result.ok ? '命令执行完成' : result.stderr || '命令执行失败')
    await load()
  } finally { actingId.value = null }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="skeleton-stack"><div /><div /><div /></div>
  <div v-else class="dashboard-layout">
    <div class="metrics-row">
      <MetricBlock label="Services" :value="String(services.length)" />
      <MetricBlock label="Healthy" :value="String(healthyCount)" accent />
      <MetricBlock label="Models" :value="String(modelCount)" />
      <MetricBlock label="Recent tests" :value="String(Math.min(benchmarks.length, 5))" />
    </div>

    <PageSection title="Llama Services" description="每个服务都使用独立的 unit、端口和模型配置。">
      <div v-if="!services.length" class="empty-state">
        还没有服务。<RouterLink to="/services">创建第一个 Llama Service</RouterLink>
      </div>
      <div v-else class="service-card-grid">
        <article v-for="service in services" :key="service.id" class="service-hero service-card">
          <div>
            <span class="service-kicker"><IconServer :size="17" /> {{ service.unit_name }}</span>
            <h2>{{ service.name }}</h2>
            <p>{{ service.host }}:{{ service.port }} · {{ service.mode }} · {{ service.models.map((item) => item.alias).join(', ') }}</p>
          </div>
          <div class="service-controls">
            <StatusBadge :status="service.status?.ok ? 'healthy' : 'inactive'" />
            <button class="button secondary" :disabled="actingId === service.id" @click="action(service, 'start')"><IconPlayerPlay :size="17" />启动</button>
            <button class="button primary" :disabled="actingId === service.id" @click="action(service, 'restart')"><IconRefresh :size="17" />重启</button>
          </div>
        </article>
      </div>
    </PageSection>

    <PageSection title="最近 Benchmark">
      <div v-if="!benchmarks.length" class="empty-state">还没有测试记录。</div>
      <div v-else class="compact-list">
        <RouterLink v-for="job in benchmarks.slice(0, 5)" :key="job.id" to="/results" class="compact-row">
          <div><strong>{{ job.name }}</strong><span>{{ job.model_alias || '未指定模型' }} · {{ new Date(job.created_at).toLocaleString() }}</span></div>
          <StatusBadge :status="job.status" />
        </RouterLink>
      </div>
    </PageSection>
  </div>
</template>
