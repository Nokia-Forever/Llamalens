<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { IconPlayerPlay, IconRefresh, IconServer } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import MetricBlock from '../components/MetricBlock.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'

interface Summary {
  service: { ok: boolean; stdout: string; stderr: string }
  binary: { version: string | null; devices: string[]; errors: string[] }
  active_profile: { id: string; name: string; model_path: string } | null
  recent_benchmarks: Array<{ id: string; name: string; status: string; created_at: string }>
  recent_switches: Array<{ id: string; profile_id: string; status: string; message: string }>
}

const store = useAppStore()
const data = ref<Summary | null>(null)
const loading = ref(true)
const acting = ref(false)
const serviceLabel = computed(() => (data.value?.service.ok ? '运行信息可读' : '未连接'))

async function load() {
  loading.value = true
  try {
    data.value = await api<Summary>('/system/summary')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载概览失败')
  } finally {
    loading.value = false
  }
}

async function action(action: 'start' | 'restart') {
  acting.value = true
  try {
    const result = await api<{ ok: boolean; stderr: string }>('/system/action', { method: 'POST', ...jsonBody({ action }) })
    store.notify(result.ok ? 'success' : 'error', result.ok ? '命令执行完成' : result.stderr || '命令执行失败')
    await load()
  } finally {
    acting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="skeleton-stack" aria-label="正在加载"><div /><div /><div /></div>
  <div v-else-if="data" class="dashboard-layout">
    <section class="service-hero">
      <div>
        <span class="service-kicker"><IconServer :size="17" /> llama.cpp service</span>
        <h2>{{ data.active_profile?.name || '尚未激活 Profile' }}</h2>
        <p>{{ data.active_profile?.model_path || '请先在设置中连接 service，并创建 Profile。' }}</p>
      </div>
      <div class="service-controls">
        <StatusBadge :status="data.service.ok ? 'healthy' : 'inactive'" :label="serviceLabel" />
        <button class="button secondary" :disabled="acting" @click="action('start')"><IconPlayerPlay :size="17" />启动</button>
        <button class="button primary" :disabled="acting" @click="action('restart')"><IconRefresh :size="17" />重启</button>
      </div>
    </section>

    <div class="metrics-row">
      <MetricBlock label="Binary" :value="data.binary.version?.split('\n')[0] || '未探测'" />
      <MetricBlock label="Devices" :value="String(data.binary.devices.length)" :detail="data.binary.devices[0] || '暂无设备信息'" />
      <MetricBlock label="Recent tests" :value="String(data.recent_benchmarks.length)" detail="最近 5 条" />
      <MetricBlock label="Service" :value="data.service.ok ? 'Ready' : 'Check'" :accent="data.service.ok" />
    </div>

    <div class="dashboard-columns">
      <PageSection title="最近 Benchmark" description="测试请求和 Profile 分别保存快照。">
        <div v-if="!data.recent_benchmarks.length" class="empty-state">还没有测试记录。</div>
        <div v-else class="compact-list">
          <RouterLink v-for="job in data.recent_benchmarks" :key="job.id" to="/results" class="compact-row">
            <div><strong>{{ job.name }}</strong><span>{{ new Date(job.created_at).toLocaleString() }}</span></div>
            <StatusBadge :status="job.status" />
          </RouterLink>
        </div>
      </PageSection>
      <PageSection title="切换记录" description="失败任务会保留诊断和回滚信息。">
        <div v-if="!data.recent_switches.length" class="empty-state">还没有 Profile 切换记录。</div>
        <div v-else class="compact-list">
          <div v-for="job in data.recent_switches" :key="job.id" class="compact-row">
            <div><strong>{{ job.message || 'Profile 切换' }}</strong><span>{{ job.profile_id }}</span></div>
            <StatusBadge :status="job.status" />
          </div>
        </div>
      </PageSection>
    </div>
  </div>
</template>
