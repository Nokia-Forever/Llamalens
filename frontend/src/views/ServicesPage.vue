<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  IconArchive, IconCopy, IconDeviceFloppy, IconDownload, IconEdit, IconPlayerPause, IconPlayerPlay,
  IconPlus, IconRefresh, IconRestore, IconRocket, IconTemplate, IconTrash,
} from '@tabler/icons-vue'
import { useI18n } from 'vue-i18n'
import { servicesApi, profilesApi, modelsApi, argumentsApi } from '../api'
import LaunchConfigEditor from '../components/LaunchConfigEditor.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import { useBusy } from '../composables/useBusy'
import { cloneConfig } from '../utils'
import type { CatalogArgument, LaunchConfig, LlamaService, ModelFile, Profile } from '../types'

const store = useAppStore()
const { t } = useI18n()
const services = ref<LlamaService[]>([])
const profiles = ref<Profile[]>([])
const models = ref<ModelFile[]>([])
const catalog = ref<CatalogArgument[]>([])
const selectedId = ref<string | null>(null)
const profileId = ref('')
const draft = ref<LaunchConfig | null>(null)
const preview = ref('')
const { run: runBusy, isBusy } = useBusy()
const logs = ref('')
const editingDraft = ref(false)

const emptyForm = () => ({
  name: '', description: '', unit_name: '', server_bin: '/usr/local/bin/llama-server',
  service_user: 'root', service_group: 'root', working_directory: '/', host: '127.0.0.1', port: 8080,
  health_path: '/health', request_path: '/completion',
  service_type: 'exec', restart_policy: 'on-failure', restart_sec: 3,
  unit_extra_text: '', service_extra_text: '', install_extra_text: '',
})
const form = reactive(emptyForm())

const selected = computed(() => services.value.find((item) => item.id === selectedId.value) || null)
const chosenProfile = computed(() => profiles.value.find((item) => item.id === profileId.value) || null)
const sourceProfile = computed(() => profiles.value.find((item) => item.id === selected.value?.source_profile_id) || null)
const appliedProfile = computed(() => profiles.value.find((item) => item.id === selected.value?.applied_source_profile_id) || null)
const localPending = computed(() => {
  if (selected.value?.has_pending_changes) return true
  if (!draft.value) return false
  return JSON.stringify(draft.value) !== JSON.stringify(selected.value?.applied_launch_config || null)
})

function basePayload() {
  return { ...form }
}

function applyService(service: LlamaService, replaceDraft = true) {
  selectedId.value = service.id
  Object.assign(form, {
    name: service.name, description: service.description, unit_name: service.unit_name,
    server_bin: service.server_bin, service_user: service.service_user, service_group: service.service_group,
    working_directory: service.working_directory, host: service.host, port: service.port,
    health_path: service.health_path, request_path: service.request_path,
    service_type: service.service_type, restart_policy: service.restart_policy, restart_sec: service.restart_sec,
    unit_extra_text: service.unit_extra_text, service_extra_text: service.service_extra_text,
    install_extra_text: service.install_extra_text,
  })
  if (replaceDraft) draft.value = cloneConfig(service.draft_launch_config)
  profileId.value = service.source_profile_id || profiles.value[0]?.id || ''
  preview.value = service.rendered_unit
  logs.value = ''
}

async function fetchServices(selectId?: string, replaceDraft = true) {
  services.value = await servicesApi.list({ include_archived: true, with_status: true })
  const target = services.value.find((item) => item.id === (selectId || selectedId.value))
  if (target) applyService(target, replaceDraft)
}

async function load() {
  const [profilesPage, modelsPage, catalogData] = await Promise.all([
    profilesApi.list({ limit: 200 }),
    modelsApi.list({ limit: 200 }),
    argumentsApi.list({ limit: 1000 }),
  ])
  profiles.value = profilesPage.items
  models.value = modelsPage.items
  catalog.value = catalogData
  await fetchServices()
  if (!selectedId.value && services.value.length) applyService(services.value[0])
  if (!profileId.value) profileId.value = profiles.value[0]?.id || ''
}

function reset() {
  selectedId.value = null
  Object.assign(form, emptyForm())
  profileId.value = profiles.value[0]?.id || ''
  draft.value = null
  preview.value = ''
  logs.value = ''
  editingDraft.value = false
}

function profileSummary(profile: Profile | null) {
  if (!profile) return t('services.noProfileSelected')
  if (profile.mode === 'single') return t('services.singleSummary', { alias: profile.model_alias })
  const aliases = profile.models.filter((item) => item.enabled).map((item) => item.alias)
  return t('services.routerSummary', { count: aliases.length, aliases: aliases.join(', ') })
}

function draftSummary(config: LaunchConfig | null) {
  if (!config) return t('services.noLaunchTemplate')
  if (config.mode === 'single') return t('services.singleSummary', { alias: config.model_alias })
  return t('services.routerDraftSummary', { aliases: config.models.filter((item) => item.enabled).map((item) => item.alias).join(', ') })
}

async function saveBase(silent = false) {
  const saved = selectedId.value
    ? await servicesApi.update(selectedId.value, basePayload())
    : await servicesApi.create(basePayload())
  selectedId.value = saved.id
  await fetchServices(saved.id, false)
  if (!silent) store.notify('success', t('services.baseSaved'))
  return saved
}

async function save() {
  await runBusy('service.save', async () => {
    try {
      await saveBase()
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('services.saveFailed'))
    }
  })
}

async function importProfile() {
  const serviceId = selectedId.value
  if (!serviceId) return store.notify('error', t('services.saveFirst'))
  if (!profileId.value) return store.notify('error', t('services.selectProfilePrompt'))
  if (draft.value && !confirm(t('services.importConfirm'))) return
  await runBusy('service.importProfile', async () => {
    try {
      const service = await servicesApi.selectProfile(serviceId, profileId.value)
      await fetchServices(service.id)
      editingDraft.value = true
      store.notify('success', t('services.importedIndependent'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('services.importFailed'))
    }
  })
}

async function saveDraft(silent = false) {
  await runBusy('service.saveDraft', async () => {
    if (!selectedId.value || !draft.value) throw new Error(t('services.importFirst'))
    const service = await servicesApi.updateLaunchConfig(selectedId.value, draft.value)
    draft.value = cloneConfig(service.draft_launch_config)
    await fetchServices(service.id, false)
    if (!silent) store.notify('success', t('services.draftSavedPending'))
  })
}

async function persistDisplayedConfig() {
  await saveBase(true)
  if (!draft.value) throw new Error(t('services.importLaunchFirst'))
  await saveDraft(true)
}

async function renderPreview() {
  const serviceId = selectedId.value
  if (!serviceId) return store.notify('error', t('services.saveFirst'))
  await runBusy('service.preview', async () => {
    try {
      await persistDisplayedConfig()
      const result = await servicesApi.previewUnit(serviceId)
      preview.value = result.content
      store.notify('success', t('services.previewGenerated'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('services.previewFailed'))
    }
  })
}

async function deploy() {
  const serviceId = selectedId.value
  if (!serviceId) return store.notify('error', t('services.saveFirst'))
  await runBusy('service.deploy', async () => {
    try {
      await persistDisplayedConfig()
      const result = await servicesApi.deploy(serviceId)
      if (!result.ok) throw new Error(t('services.deployCommandFailed'))
      store.notify('success', t('services.deploySuccess'))
      await fetchServices(serviceId)
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('services.deployFailed'))
    }
  })
}

async function action(value: 'start' | 'stop' | 'restart') {
  const serviceId = selectedId.value
  if (!serviceId) return
  await runBusy(`service.${value}`, async () => {
    try {
      const result = await servicesApi.action(serviceId, value)
      store.notify(result.ok ? 'success' : 'error', result.ok ? t('services.actionDone', { action: t(`services.${value}`) }) : result.stderr || t('services.actionFailed', { action: t(`services.${value}`) }))
      await fetchServices(serviceId, false)
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('services.actionFailed', { action: t(`services.${value}`) }))
    }
  })
}

async function showLogs() {
  const serviceId = selectedId.value
  if (!serviceId) return
  try {
    const result = await servicesApi.logs(serviceId)
    logs.value = result.stdout || result.stderr || t('services.noLogs')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('services.logsFailed'))
  }
}

async function archive() {
  const serviceId = selectedId.value
  if (!serviceId || !confirm(t('services.archiveConfirm'))) return
  await runBusy('service.archive', async () => {
    await servicesApi.archive(serviceId)
    store.notify('success', t('services.archived'))
    await fetchServices(serviceId)
  })
}

async function restore() {
  const serviceId = selectedId.value
  if (!serviceId) return
  await runBusy('service.restore', async () => {
    await servicesApi.restore(serviceId)
    store.notify('success', t('services.restoreSuccess'))
    await fetchServices(serviceId)
  })
}

async function remove() {
  const serviceId = selectedId.value
  if (!serviceId || !confirm(t('services.deleteFullConfirm'))) return
  await runBusy('service.delete', async () => {
    await servicesApi.delete(serviceId)
    store.notify('success', t('services.deleted'))
    reset()
    await fetchServices()
  })
}

async function copyPreview() {
  await navigator.clipboard.writeText(preview.value)
  store.notify('success', t('services.unitCopied'))
}

function downloadPreview() {
  const blob = new Blob([preview.value], { type: 'text/plain;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = form.unit_name || 'llamalens.service'
  link.click()
  URL.revokeObjectURL(link.href)
}

onMounted(load)
</script>

<template>
  <div class="profile-workspace service-workspace">
    <aside class="profile-list-pane">
      <div class="pane-heading">
        <strong>{{ t('services.title') }}</strong>
        <button class="icon-button" type="button" :aria-label="t('services.new')" @click="reset"><IconPlus :size="18" /></button>
      </div>
      <button v-for="service in services" :key="service.id" class="profile-list-item" :class="{ active: selectedId === service.id }" @click="applyService(service)">
        <span><strong>{{ service.name }}</strong><small>{{ service.unit_name }} · {{ service.host }}:{{ service.port }}</small></span>
        <StatusBadge :status="service.archived_at ? 'archived' : service.status?.ok ? 'active' : 'inactive'" />
      </button>
      <div v-if="!services.length" class="empty-state compact">{{ t('services.noLlamaServices') }}</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div>
          <h2>{{ selectedId ? t('services.editService') : t('services.createService') }}</h2>
          <p>{{ t('services.description') }}</p>
        </div>
        <button class="button primary" :disabled="isBusy('service.save')"><IconDeviceFloppy :size="17" />{{ selectedId ? t('services.saveBase') : t('services.createService') }}</button>
      </div>

      <PageSection :title="t('services.baseConfig')">
        <div class="form-grid two-columns">
          <label class="field"><span>{{ t('services.serviceName') }}</span><input v-model.trim="form.name" required /></label>
          <label class="field"><span>{{ t('services.unitName') }}</span><input v-model.trim="form.unit_name" :disabled="!!selectedId" :placeholder="t('services.unitNamePlaceholder')" /></label>
          <label class="field"><span>{{ t('services.fieldDescription') }}</span><input v-model="form.description" :placeholder="t('services.descriptionPlaceholder')" /></label>
          <label class="field"><span>{{ t('services.serverPath') }}</span><input v-model.trim="form.server_bin" required /></label>
          <label class="field"><span>WorkingDirectory</span><input v-model.trim="form.working_directory" required /></label>
          <label class="field"><span>User</span><input v-model.trim="form.service_user" required /></label>
          <label class="field"><span>Group</span><input v-model.trim="form.service_group" required /></label>
          <label class="field"><span>Host</span><input v-model.trim="form.host" required /></label>
          <label class="field"><span>Port</span><input v-model.number="form.port" type="number" min="1" max="65535" required /></label>
          <label class="field"><span>{{ t('services.healthPath') }}</span><input v-model.trim="form.health_path" required /></label>
          <label class="field"><span>{{ t('services.benchmarkPath') }}</span><input v-model.trim="form.request_path" required /></label>
        </div>
      </PageSection>

      <PageSection :title="t('services.processPolicy')" :description="t('services.processPolicyDesc')">
        <div class="form-grid two-columns">
          <label class="field">
            <span>Type</span>
            <select v-model="form.service_type">
              <option value="simple">simple</option>
              <option value="exec">exec</option>
              <option value="forking">forking</option>
              <option value="oneshot">oneshot</option>
              <option value="dbus">dbus</option>
              <option value="notify">notify</option>
              <option value="notify-reload">notify-reload</option>
              <option value="idle">idle</option>
            </select>
          </label>
          <label class="field">
            <span>Restart</span>
            <select v-model="form.restart_policy">
              <option value="no">no</option>
              <option value="on-success">on-success</option>
              <option value="on-failure">on-failure</option>
              <option value="on-abnormal">on-abnormal</option>
              <option value="on-watchdog">on-watchdog</option>
              <option value="on-abort">on-abort</option>
              <option value="always">always</option>
            </select>
          </label>
          <label class="field"><span>{{ t('services.restartSeconds') }}</span><input v-model.number="form.restart_sec" type="number" min="0" step="1" required /></label>
        </div>
      </PageSection>

      <PageSection :title="t('services.startProfile')" :description="t('services.startProfileDesc')">
        <div v-if="!selectedId" class="empty-state compact">{{ t('services.createBeforeImport') }}</div>
        <template v-else>
          <div class="profile-import-row">
            <label class="field"><span>{{ t('services.selectProfile') }}</span><select v-model="profileId"><option value="" disabled>{{ t('services.selectProfile') }}</option><option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option></select></label>
            <div class="profile-import-summary"><strong>{{ chosenProfile?.name || t('services.notSelected') }}</strong><span>{{ profileSummary(chosenProfile) }}</span></div>
            <button type="button" class="button secondary" :disabled="isBusy('service.importProfile') || !profileId" @click="importProfile"><IconTemplate :size="17" />{{ t('services.importProfile') }}</button>
          </div>
          <div v-if="!profiles.length" class="risk-banner neutral">{{ t('services.noProfiles') }}</div>

          <div class="local-copy-card" :class="{ pending: localPending }">
            <div>
              <span class="service-kicker">{{ t('services.localCopy') }}</span>
              <strong>{{ draftSummary(draft) }}</strong>
              <small>{{ t('services.source') }}：{{ sourceProfile?.name || (selected?.source_profile_id ? t('services.sourceDeleted') : t('services.noSource')) }}。{{ t('services.copyIndependent') }}</small>
            </div>
            <div class="inline-actions">
              <StatusBadge :status="localPending ? 'pending' : selected?.applied_launch_config ? 'applied' : 'draft'" :label="localPending ? t('services.pendingChanges') : selected?.applied_launch_config ? t('services.applied') : t('services.draftOnly')" />
              <button v-if="draft" type="button" class="button secondary" @click="editingDraft = !editingDraft"><IconEdit :size="17" />{{ editingDraft ? t('services.collapseEditor') : t('services.editLocalCopy') }}</button>
            </div>
          </div>

          <div v-if="draft && editingDraft" class="local-copy-editor">
            <LaunchConfigEditor :config="draft" :models="models" :catalog="catalog" />
            <div class="inline-actions editor-save-row">
              <span class="muted-copy">{{ t('services.draftOnlyHint') }}</span>
              <button type="button" class="button secondary" :disabled="isBusy('service.saveDraft')" @click="saveDraft().catch((error) => store.notify('error', error.message))"><IconDeviceFloppy :size="17" />{{ t('services.saveDraft') }}</button>
            </div>
          </div>
        </template>
      </PageSection>

      <PageSection :title="t('services.systemdCustom')" :description="t('services.systemdCustomDesc')">
        <div class="unit-section-grid">
          <label class="field"><span>{{ t('services.unitExtra') }}</span><textarea v-model="form.unit_extra_text" rows="6" placeholder="RequiresMountsFor=/opt/models" /></label>
          <label class="field"><span>{{ t('services.serviceExtra') }}</span><textarea v-model="form.service_extra_text" rows="6" placeholder="Environment=CUDA_VISIBLE_DEVICES=0&#10;LimitNOFILE=1048576" /></label>
          <label class="field"><span>{{ t('services.installExtra') }}</span><textarea v-model="form.install_extra_text" rows="6" placeholder="Alias=my-llama.service" /></label>
        </div>
      </PageSection>

      <PageSection :title="t('services.unitPreview')" :description="t('services.unitPreviewDesc')">
        <div class="inline-actions preview-actions">
          <button type="button" class="button secondary" :disabled="isBusy('service.preview') || !draft" @click="renderPreview"><IconRefresh :size="17" />{{ t('services.preview') }}</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="copyPreview"><IconCopy :size="17" />{{ t('services.copy') }}</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="downloadPreview"><IconDownload :size="17" />{{ t('services.download') }}</button>
        </div>
        <pre class="code-block unit-preview">{{ preview || t('services.previewHint') }}</pre>
      </PageSection>

      <div v-if="selectedId" class="sticky-actions service-actions">
        <span v-if="selected?.applied_launch_config" class="applied-source">{{ t('services.appliedSource') }}：{{ appliedProfile?.name || t('services.localHistoryTemplate') }}</span>
        <button type="button" class="button primary" :disabled="isBusy('service.deploy') || !draft || !!selected?.archived_at" @click="deploy"><IconRocket :size="17" />{{ t('services.deploy') }}</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at || isBusy('service.start')" @click="action('start')"><IconPlayerPlay :size="17" />{{ t('services.start') }}</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at || isBusy('service.stop')" @click="action('stop')"><IconPlayerPause :size="17" />{{ t('services.stop') }}</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at || isBusy('service.restart')" @click="action('restart')"><IconRefresh :size="17" />{{ t('services.restart') }}</button>
        <button type="button" class="button secondary" @click="showLogs">{{ t('services.logs') }}</button>
        <button v-if="!selected?.archived_at" type="button" class="button secondary" :disabled="isBusy('service.archive')" @click="archive"><IconArchive :size="17" />{{ t('services.archive') }}</button>
        <button v-else type="button" class="button secondary" :disabled="isBusy('service.restore')" @click="restore"><IconRestore :size="17" />{{ t('services.restore') }}</button>
        <button type="button" class="button danger" :disabled="isBusy('service.delete')" @click="remove"><IconTrash :size="17" />{{ t('services.deletePermanently') }}</button>
      </div>
      <pre v-if="logs" class="code-block">{{ logs }}</pre>
    </form>
  </div>
</template>
