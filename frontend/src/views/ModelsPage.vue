<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconCloudDownload, IconDatabaseSearch, IconPlayerStop, IconRefresh, IconSearch } from '@tabler/icons-vue'
import { modelsApi, settingsApi } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { AppSettings, DownloadJob, ModelFile, RemoteModel } from '../types'

const store = useAppStore()
const { t } = useI18n()
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
  const [modelsPage, settingsData, downloadsPage] = await Promise.all([
    modelsApi.list(),
    settingsApi.get(),
    modelsApi.listDownloads(),
  ])
  models.value = modelsPage.items
  settings.value = settingsData
  downloads.value = downloadsPage.items
  if (!selectedRoot.value) selectedRoot.value = settings.value?.model_roots[0] || ''
}
async function scan() {
  try {
    const result = await modelsApi.scan()
    store.notify('success', t('models.scannedFound', { count: result.found }))
    await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : t('models.scanFailed')) }
}
async function searchRemote() {
  if (remoteQuery.value.trim().length < 2) return
  remoteLoading.value = true
  try { remote.value = await modelsApi.remoteSearch(remoteQuery.value) }
  catch (error) { store.notify('error', error instanceof Error ? error.message : t('models.remoteSearchFailed')) }
  finally { remoteLoading.value = false }
}
async function download(file: { name: string; url: string }) {
  const root = selectedRoot.value
  if (!root) return store.notify('error', t('models.addRootFirst'))
  try {
    await modelsApi.createDownload({ url: file.url, target_root: root, filename: file.name })
    store.notify('success', t('models.downloadStarted'))
    await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : t('models.downloadFailed')) }
}
async function cancelDownload(id: string) {
  try {
    await modelsApi.cancelDownload(id)
    store.notify('info', t('models.downloadCanceled'))
  } catch (error) { store.notify('error', error instanceof Error ? error.message : t('models.cancelFailed')) }
}
onMounted(async () => {
  await load()
  timer = window.setInterval(async () => {
    try {
      const page = await modelsApi.listDownloads()
      downloads.value = page.items
    } catch { /* keep the last known list */ }
  }, 2200)
})
onBeforeUnmount(() => timer && clearInterval(timer))
</script>

<template>
  <div class="page-stack">
    <PageSection :title="t('models.localModels')" :description="t('models.localDesc')">
      <template #actions>
        <div class="inline-actions">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" :placeholder="t('models.searchFilePlaceholder')" /></label>
          <button class="button primary" @click="scan"><IconRefresh :size="17" />{{ t('models.scanDir') }}</button>
        </div>
      </template>
      <div v-if="!filtered.length" class="empty-state">{{ t('models.localEmpty') }}</div>
      <div v-else class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>{{ t('models.model') }}</th><th>{{ t('models.quantization') }}</th><th>{{ t('models.size') }}</th><th>{{ t('common.status') }}</th><th>{{ t('models.path') }}</th></tr></thead>
          <tbody><tr v-for="model in filtered" :key="model.id">
            <td><strong>{{ model.name }}</strong></td><td><code>{{ model.quantization || t('common.unknown') }}</code></td>
            <td>{{ bytes(model.size_bytes) }}</td><td><StatusBadge :status="model.available ? 'active' : 'inactive'" :label="model.available ? t('models.available') : t('models.missing')" /></td>
            <td class="path-cell" :title="model.path">{{ model.path }}</td>
          </tr></tbody>
        </table>
      </div>
    </PageSection>

    <PageSection :title="t('models.onlineSearch')" :description="t('models.remoteDesc')">
      <template #actions>
        <form class="inline-actions" @submit.prevent="searchRemote">
          <select v-model="selectedRoot" class="compact-select" :aria-label="t('models.targetRoot')"><option v-for="root in settings?.model_roots || []" :key="root" :value="root">{{ root }}</option></select>
          <label class="search-box"><IconDatabaseSearch :size="17" /><input v-model="remoteQuery" :placeholder="t('models.remoteSearchPlaceholder')" /></label>
          <button class="button secondary" :disabled="remoteLoading">{{ t('common.search') }}</button>
        </form>
      </template>
      <div v-if="!remote.length" class="empty-state">{{ t('models.remoteSearchHint') }}</div>
      <div v-else class="remote-grid">
        <article v-for="model in remote" :key="model.model_id" class="remote-model">
          <header><strong>{{ model.model_id }}</strong><span>{{ model.downloads.toLocaleString() }} downloads</span></header>
          <div class="file-list">
            <div v-for="file in model.files.slice(0, 8)" :key="file.name" class="file-row">
              <span>{{ file.name }}</span>
              <button class="icon-button" :title="t('models.downloadFile', { name: file.name })" @click="download(file)"><IconCloudDownload :size="18" /></button>
            </div>
          </div>
        </article>
      </div>
    </PageSection>

    <PageSection :title="t('models.downloadTasks')">
      <div v-if="!downloads.length" class="empty-state">{{ t('models.noDownloads') }}</div>
      <div v-else class="compact-list">
        <div v-for="job in downloads" :key="job.id" class="download-row">
          <div><strong>{{ job.target_path.split(/[\\/]/).pop() }}</strong><span>{{ bytes(job.downloaded_bytes) }}<template v-if="job.total_bytes"> / {{ bytes(job.total_bytes) }}</template></span></div>
          <StatusBadge :status="job.status" />
          <button v-if="['queued', 'running'].includes(job.status)" class="icon-button danger" :aria-label="t('models.cancelDownload')" @click="cancelDownload(job.id)"><IconPlayerStop :size="17" /></button>
          <small v-if="job.error" class="error-text">{{ job.error }}</small>
        </div>
      </div>
    </PageSection>
  </div>
</template>
