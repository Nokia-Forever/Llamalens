<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPlayerPlay, IconRefresh, IconServer } from '@tabler/icons-vue'
import { benchmarksApi, profilesApi, servicesApi } from '../api'
import MetricBlock from '../components/MetricBlock.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkJob, LlamaService, Profile } from '../types'

const store = useAppStore()
const { t } = useI18n()
const services = ref<LlamaService[]>([])
const profiles = ref<Profile[]>([])
const benchmarks = ref<BenchmarkJob[]>([])
const loading = ref(true)
const actingId = ref<string | null>(null)
const healthyCount = computed(() => services.value.filter((item) => item.status?.ok).length)
const modelCount = computed(() => services.value.reduce((total, item) => total + item.applied_model_aliases.length, 0))

function profileName(id: string | null) {
  if (!id) return t('dashboard.localNoSource')
  return profiles.value.find((profile) => profile.id === id)?.name || t('dashboard.historyProfile')
}

async function load() {
  loading.value = true
  try {
    const [servicesData, benchmarksPage, profilesPage] = await Promise.all([
      servicesApi.list({ with_status: true }),
      benchmarksApi.list({ limit: 10 }),
      profilesApi.list({ limit: 200 }),
    ])
    services.value = servicesData
    benchmarks.value = benchmarksPage.items
    profiles.value = profilesPage.items
  } catch (error) { store.notify('error', error instanceof Error ? error.message : t('dashboard.loadFailed')) }
  finally { loading.value = false }
}

async function action(service: LlamaService, value: 'start' | 'restart') {
  actingId.value = service.id
  try {
    const result = await servicesApi.action(service.id, value)
    store.notify(result.ok ? 'success' : 'error', result.ok ? t('dashboard.commandDone') : result.stderr || t('dashboard.commandFailed'))
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

    <PageSection title="Llama Services" :description="t('dashboard.servicesDesc')">
      <div v-if="!services.length" class="empty-state">
        {{ t('dashboard.noServices') }}<RouterLink to="/services">{{ t('dashboard.createFirstService') }}</RouterLink>
      </div>
      <div v-else class="service-card-grid">
        <article v-for="service in services" :key="service.id" class="service-hero service-card">
          <div>
            <span class="service-kicker"><IconServer :size="17" /> {{ service.unit_name }}</span>
            <h2>{{ service.name }}</h2>
            <p>{{ service.host }}:{{ service.port }} · {{ service.applied_launch_config?.mode || t('dashboard.notDeployed') }} · {{ service.applied_model_aliases.join(', ') || t('dashboard.noAppliedAlias') }}</p>
            <small class="service-profile-source">{{ t('dashboard.appliedSource') }}：{{ profileName(service.applied_source_profile_id) }}</small>
          </div>
          <div class="service-controls">
            <StatusBadge :status="service.status?.ok ? 'healthy' : 'inactive'" />
            <StatusBadge v-if="service.has_pending_changes" status="pending" :label="t('dashboard.pendingChanges')" />
            <button class="button secondary" :disabled="actingId === service.id" @click="action(service, 'start')"><IconPlayerPlay :size="17" />{{ t('services.start') }}</button>
            <button class="button primary" :disabled="actingId === service.id" @click="action(service, 'restart')"><IconRefresh :size="17" />{{ t('services.restart') }}</button>
          </div>
        </article>
      </div>
    </PageSection>

    <PageSection :title="t('dashboard.recentBenchmarks')">
      <div v-if="!benchmarks.length" class="empty-state">{{ t('dashboard.noBenchmarkRecords') }}</div>
      <div v-else class="compact-list">
        <RouterLink v-for="job in benchmarks.slice(0, 5)" :key="job.id" to="/results" class="compact-row">
          <div><strong>{{ job.name }}</strong><span>{{ job.model_alias || t('dashboard.noModelSpecified') }} · {{ formatDate(job.created_at) }}</span></div>
          <StatusBadge :status="job.status" />
        </RouterLink>
      </div>
    </PageSection>
  </div>
</template>
