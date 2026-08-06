<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { IconCloudDownload, IconDatabaseSearch, IconPlayerStop, IconRefresh, IconSearch } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { AppSettings, ModelFile } from '../types'

interface RemoteModel { model_id: string; downloads: number; likes: number; files: Array<{ name: string; url: string }> }
interface DownloadJob { id: string; target_path: string; status: string; downloaded_bytes: number; total_bytes: number | null; error: string | null }

const store = useAppStore()
const models = ref<ModelFile[]>([])
const settings = ref<AppSettings | null>(null)
const query = ref('')
const remoteQuery = ref('')
const remote = ref<RemoteModel[]>([])
const remoteLoading = ref(false)
const downloads = ref<DownloadJob[]>([])
const selectedRoot = ref('')
let timer: number | undefined

const filtered = computed(() => {
  const needle = query.value.toLowerCase()
  return models.value.filter((model) => `${model.name} ${model.path} ${model.quantization || ''}`.toLowerCase().includes(needle))
})
const bytes = (value: number) => value > 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(2)} GB` : `${(value / 1024 ** 2).toFixed(1)} MB`

async function load() {
  ;[models.value, settings.value, downloads.value] = await Promise.all([
    api<ModelFile[]>('/models'), api<AppSettings>('/settings'), api<DownloadJob[]>('/models/downloads'),
  ])
  if (!selectedRoot.value) selectedRoot.value = settings.value?.model_roots[0] || ''
}
async function scan() {
  try {
    const result = await api<{ found: number }>('/models/scan', { method: 'POST' })
    store.notify('success', `扫描完成，发现 ${result.found} 个 GGUF`)
    await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '扫描失败') }
}
async function searchRemote() {
  if (remoteQuery.value.trim().length < 2) return
  remoteLoading.value = true
  try { remote.value = await api<RemoteModel[]>(`/models/remote-search?q=${encodeURIComponent(remoteQuery.value)}`) }
  catch (error) { store.notify('error', error instanceof Error ? error.message : '在线搜索失败') }
  finally { remoteLoading.value = false }
}
async function download(file: { name: string; url: string }) {
  const root = selectedRoot.value
  if (!root) return store.notify('error', '请先在设置中添加模型目录')
  try {
    await api('/models/downloads', { method: 'POST', ...jsonBody({ url: file.url, target_root: root, filename: file.name }) })
    store.notify('success', '下载任务已创建')
    await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '创建下载失败') }
}
async function cancelDownload(id: string) {
  try {
    await api(`/models/downloads/${id}/cancel`, { method: 'POST' })
    store.notify('info', '已请求取消下载')
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '取消失败') }
}
onMounted(async () => {
  await load()
  timer = window.setInterval(async () => {
    try { downloads.value = await api<DownloadJob[]>('/models/downloads') } catch { /* keep the last known list */ }
  }, 2200)
})
onBeforeUnmount(() => timer && clearInterval(timer))
</script>

<template>
  <div class="page-stack">
    <PageSection title="本地模型" description="只扫描设置中登记的目录，不移动或删除文件。">
      <template #actions>
        <div class="inline-actions">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" placeholder="搜索文件、量化或路径" /></label>
          <button class="button primary" @click="scan"><IconRefresh :size="17" />扫描目录</button>
        </div>
      </template>
      <div v-if="!filtered.length" class="empty-state">没有本地 GGUF。添加目录后点击扫描。</div>
      <div v-else class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>模型</th><th>量化</th><th>大小</th><th>状态</th><th>路径</th></tr></thead>
          <tbody><tr v-for="model in filtered" :key="model.id">
            <td><strong>{{ model.name }}</strong></td><td><code>{{ model.quantization || '未知' }}</code></td>
            <td>{{ bytes(model.size_bytes) }}</td><td><StatusBadge :status="model.available ? 'active' : 'inactive'" :label="model.available ? '可用' : '缺失'" /></td>
            <td class="path-cell" :title="model.path">{{ model.path }}</td>
          </tr></tbody>
        </table>
      </div>
    </PageSection>

    <PageSection title="在线搜索" description="搜索 Hugging Face 上公开的 GGUF 文件并下载到指定模型目录。">
      <template #actions>
        <form class="inline-actions" @submit.prevent="searchRemote">
          <select v-model="selectedRoot" class="compact-select" aria-label="下载目标目录"><option v-for="root in settings?.model_roots || []" :key="root" :value="root">{{ root }}</option></select>
          <label class="search-box"><IconDatabaseSearch :size="17" /><input v-model="remoteQuery" placeholder="例如 Qwen3 GGUF" /></label>
          <button class="button secondary" :disabled="remoteLoading">搜索</button>
        </form>
      </template>
      <div v-if="!remote.length" class="empty-state">输入至少两个字符开始在线搜索。</div>
      <div v-else class="remote-grid">
        <article v-for="model in remote" :key="model.model_id" class="remote-model">
          <header><strong>{{ model.model_id }}</strong><span>{{ model.downloads.toLocaleString() }} downloads</span></header>
          <div class="file-list">
            <div v-for="file in model.files.slice(0, 8)" :key="file.name" class="file-row">
              <span>{{ file.name }}</span>
              <button class="icon-button" :title="`下载 ${file.name}`" @click="download(file)"><IconCloudDownload :size="18" /></button>
            </div>
          </div>
        </article>
      </div>
    </PageSection>

    <PageSection title="下载任务">
      <div v-if="!downloads.length" class="empty-state">暂无下载任务。</div>
      <div v-else class="compact-list">
        <div v-for="job in downloads" :key="job.id" class="download-row">
          <div><strong>{{ job.target_path.split(/[\\/]/).pop() }}</strong><span>{{ bytes(job.downloaded_bytes) }}<template v-if="job.total_bytes"> / {{ bytes(job.total_bytes) }}</template></span></div>
          <StatusBadge :status="job.status" />
          <button v-if="['queued', 'running'].includes(job.status)" class="icon-button danger" aria-label="取消下载" @click="cancelDownload(job.id)"><IconPlayerStop :size="17" /></button>
          <small v-if="job.error" class="error-text">{{ job.error }}</small>
        </div>
      </div>
    </PageSection>
  </div>
</template>
