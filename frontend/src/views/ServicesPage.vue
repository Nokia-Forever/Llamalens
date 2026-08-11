<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  IconArchive, IconCopy, IconDeviceFloppy, IconDownload, IconEdit, IconPlayerPause, IconPlayerPlay,
  IconPlus, IconRefresh, IconRestore, IconRocket, IconTemplate, IconTrash,
} from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import LaunchConfigEditor from '../components/LaunchConfigEditor.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { CatalogArgument, LaunchConfig, LlamaService, ModelFile, Profile } from '../types'

const store = useAppStore()
const services = ref<LlamaService[]>([])
const profiles = ref<Profile[]>([])
const models = ref<ModelFile[]>([])
const catalog = ref<CatalogArgument[]>([])
const selectedId = ref<string | null>(null)
const profileId = ref('')
const draft = ref<LaunchConfig | null>(null)
const preview = ref('')
const busy = ref(false)
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

function cloneConfig(config: LaunchConfig | null): LaunchConfig | null {
  return config ? JSON.parse(JSON.stringify(config)) as LaunchConfig : null
}

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
  services.value = await api<LlamaService[]>('/services?include_archived=true&with_status=true')
  const target = services.value.find((item) => item.id === (selectId || selectedId.value))
  if (target) applyService(target, replaceDraft)
}

async function load() {
  ;[profiles.value, models.value, catalog.value] = await Promise.all([
    api<Profile[]>('/profiles'), api<ModelFile[]>('/models'), api<CatalogArgument[]>('/arguments?limit=1000'),
  ])
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
  if (!profile) return '未选择 Profile'
  if (profile.mode === 'single') return `单模型 · ${profile.model_alias}`
  const aliases = profile.models.filter((item) => item.enabled).map((item) => item.alias)
  return `Router · ${aliases.length} 个模型 · ${aliases.join(', ')}`
}

function draftSummary(config: LaunchConfig | null) {
  if (!config) return '尚未导入启动模板'
  if (config.mode === 'single') return `单模型 · ${config.model_alias}`
  return `Router · ${config.models.filter((item) => item.enabled).map((item) => item.alias).join(', ')}`
}

async function saveBase(silent = false) {
  const saved = selectedId.value
    ? await api<LlamaService>(`/services/${selectedId.value}`, { method: 'PATCH', ...jsonBody(basePayload()) })
    : await api<LlamaService>('/services', { method: 'POST', ...jsonBody(basePayload()) })
  selectedId.value = saved.id
  await fetchServices(saved.id, false)
  if (!silent) store.notify('success', 'Service 基础与 systemd 配置已保存')
  return saved
}

async function save() {
  busy.value = true
  try {
    await saveBase()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function importProfile() {
  if (!selectedId.value) return store.notify('error', '请先创建并保存 Service')
  if (!profileId.value) return store.notify('error', '请选择 Profile')
  if (draft.value && !confirm('导入会替换当前 Service 的本地启动副本，是否继续？')) return
  busy.value = true
  try {
    const service = await api<LlamaService>(`/services/${selectedId.value}/select-profile`, {
      method: 'POST', ...jsonBody({ profile_id: profileId.value }),
    })
    await fetchServices(service.id)
    editingDraft.value = true
    store.notify('success', '模板已复制到本 Service；后续修改不会影响原 Profile')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '导入失败')
  } finally {
    busy.value = false
  }
}

async function saveDraft(silent = false) {
  if (!selectedId.value || !draft.value) throw new Error('请先导入 Profile')
  const service = await api<LlamaService>(`/services/${selectedId.value}/launch-config`, {
    method: 'PATCH', ...jsonBody(draft.value),
  })
  draft.value = cloneConfig(service.draft_launch_config)
  await fetchServices(service.id, false)
  if (!silent) store.notify('success', '本 Service 的启动副本已保存，尚未部署')
}

async function persistDisplayedConfig() {
  await saveBase(true)
  if (!draft.value) throw new Error('请先从 Profile 导入启动配置')
  await saveDraft(true)
}

async function renderPreview() {
  busy.value = true
  try {
    await persistDisplayedConfig()
    const result = await api<{ content: string }>(`/services/${selectedId.value}/preview-unit`, { method: 'POST' })
    preview.value = result.content
    store.notify('success', '已按当前 Service 草稿生成预览，未写入 systemd')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '预览失败')
  } finally {
    busy.value = false
  }
}

async function deploy() {
  if (!selectedId.value) return store.notify('error', '请先保存 Service')
  busy.value = true
  try {
    await persistDisplayedConfig()
    const result = await api<{ ok: boolean }>(`/services/${selectedId.value}/deploy`, { method: 'POST' })
    if (!result.ok) throw new Error('部署命令执行失败，上一份 applied 配置保持不变')
    store.notify('success', 'unit 已写入并执行 daemon-reload、enable --now 与 status')
    await fetchServices(selectedId.value)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '部署失败')
  } finally {
    busy.value = false
  }
}

async function action(value: 'start' | 'stop' | 'restart') {
  if (!selectedId.value) return
  try {
    const result = await api<{ ok: boolean; stderr: string }>(`/services/${selectedId.value}/action`, {
      method: 'POST', ...jsonBody({ action: value }),
    })
    store.notify(result.ok ? 'success' : 'error', result.ok ? `${value} 已完成` : result.stderr || `${value} 失败`)
    await fetchServices(selectedId.value, false)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : `${value} 失败`)
  }
}

async function showLogs() {
  if (!selectedId.value) return
  try {
    const result = await api<{ stdout: string; stderr: string }>(`/services/${selectedId.value}/logs`)
    logs.value = result.stdout || result.stderr || '暂无日志。'
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '读取日志失败')
  }
}

async function archive() {
  if (!selectedId.value || !confirm('停止、禁用并归档这个服务？')) return
  await api(`/services/${selectedId.value}/archive`, { method: 'POST' })
  store.notify('success', '服务已归档')
  await fetchServices(selectedId.value)
}

async function restore() {
  if (!selectedId.value) return
  await api(`/services/${selectedId.value}/restore`, { method: 'POST' })
  store.notify('success', '服务文件已恢复，请按需重新部署')
  await fetchServices(selectedId.value)
}

async function remove() {
  if (!selectedId.value || !confirm('彻底停止、禁用并删除 unit 与 Service 配置？模型文件不会删除。')) return
  await api(`/services/${selectedId.value}`, { method: 'DELETE' })
  store.notify('success', 'Service 与 unit 文件已删除')
  reset()
  await fetchServices()
}

async function copyPreview() {
  await navigator.clipboard.writeText(preview.value)
  store.notify('success', 'unit 内容已复制')
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
        <strong>Services</strong>
        <button class="icon-button" type="button" aria-label="新建服务" @click="reset"><IconPlus :size="18" /></button>
      </div>
      <button v-for="service in services" :key="service.id" class="profile-list-item" :class="{ active: selectedId === service.id }" @click="applyService(service)">
        <span><strong>{{ service.name }}</strong><small>{{ service.unit_name }} · {{ service.host }}:{{ service.port }}</small></span>
        <StatusBadge :status="service.archived_at ? 'archived' : service.status?.ok ? 'active' : 'inactive'" />
      </button>
      <div v-if="!services.length" class="empty-state compact">还没有 Llama Service。</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div>
          <h2>{{ selectedId ? '编辑 Service' : '创建 Service' }}</h2>
          <p>Service 只负责运行环境和 systemd；模型与 llama 参数从 Profile 复制为本地草稿。</p>
        </div>
        <button class="button primary" :disabled="busy"><IconDeviceFloppy :size="17" />{{ selectedId ? '保存基础配置' : '创建 Service' }}</button>
      </div>

      <PageSection title="基础配置">
        <div class="form-grid two-columns">
          <label class="field"><span>服务名称</span><input v-model.trim="form.name" required /></label>
          <label class="field"><span>Unit 名称</span><input v-model.trim="form.unit_name" :disabled="!!selectedId" placeholder="自动生成 llamalens-*.service" /></label>
          <label class="field"><span>描述</span><input v-model="form.description" placeholder="显示在 systemctl status 中" /></label>
          <label class="field"><span>llama-server 路径</span><input v-model.trim="form.server_bin" required /></label>
          <label class="field"><span>WorkingDirectory</span><input v-model.trim="form.working_directory" required /></label>
          <label class="field"><span>User</span><input v-model.trim="form.service_user" required /></label>
          <label class="field"><span>Group</span><input v-model.trim="form.service_group" required /></label>
          <label class="field"><span>Host</span><input v-model.trim="form.host" required /></label>
          <label class="field"><span>Port</span><input v-model.number="form.port" type="number" min="1" max="65535" required /></label>
          <label class="field"><span>健康检查路径</span><input v-model.trim="form.health_path" required /></label>
          <label class="field"><span>Benchmark 请求路径</span><input v-model.trim="form.request_path" required /></label>
        </div>
      </PageSection>

      <PageSection title="Service 进程与重启策略" description="这些指令写入 [Service] 段；Type=exec 适合前台运行的 llama-server，Restart=on-failure 可在异常退出时自动拉起。">
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
          <label class="field"><span>RestartSec（秒）</span><input v-model.number="form.restart_sec" type="number" min="0" step="1" required /></label>
        </div>
      </PageSection>

      <PageSection title="启动 Profile" description="选择只负责复制模板；不会自动部署、重启，也不会与原 Profile 保持联动。">
        <div v-if="!selectedId" class="empty-state compact">请先创建 Service，再导入 Profile 模板。</div>
        <template v-else>
          <div class="profile-import-row">
            <label class="field"><span>选择 Profile</span><select v-model="profileId"><option value="" disabled>选择 Profile</option><option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option></select></label>
            <div class="profile-import-summary"><strong>{{ chosenProfile?.name || '未选择' }}</strong><span>{{ profileSummary(chosenProfile) }}</span></div>
            <button type="button" class="button secondary" :disabled="busy || !profileId" @click="importProfile"><IconTemplate :size="17" />导入模板</button>
          </div>
          <div v-if="!profiles.length" class="risk-banner neutral">还没有 Profile，请先到 Profiles 页面创建启动模板。</div>

          <div class="local-copy-card" :class="{ pending: localPending }">
            <div>
              <span class="service-kicker">Service 本地副本</span>
              <strong>{{ draftSummary(draft) }}</strong>
              <small>来源：{{ sourceProfile?.name || (selected?.source_profile_id ? '原 Profile 已删除' : '无') }}。修改不会影响原 Profile 或其他 Service。</small>
            </div>
            <div class="inline-actions">
              <StatusBadge :status="localPending ? 'pending' : selected?.applied_launch_config ? 'applied' : 'draft'" :label="localPending ? '有未部署修改' : selected?.applied_launch_config ? '已应用' : '仅草稿'" />
              <button v-if="draft" type="button" class="button secondary" @click="editingDraft = !editingDraft"><IconEdit :size="17" />{{ editingDraft ? '收起编辑器' : '编辑本服务副本' }}</button>
            </div>
          </div>

          <div v-if="draft && editingDraft" class="local-copy-editor">
            <LaunchConfigEditor :config="draft" :models="models" :catalog="catalog" />
            <div class="inline-actions editor-save-row">
              <span class="muted-copy">这里只保存草稿，不会触发 systemd 操作。</span>
              <button type="button" class="button secondary" :disabled="busy" @click="saveDraft().catch((error) => store.notify('error', error.message))"><IconDeviceFloppy :size="17" />保存本地副本</button>
            </div>
          </div>
        </template>
      </PageSection>

      <PageSection title="Systemd 自定义参数" description="每行一个 systemd 指令；内容追加到对应 section，并禁止新增 section 或重复 ExecStart。">
        <div class="unit-section-grid">
          <label class="field"><span>[Unit] 追加内容</span><textarea v-model="form.unit_extra_text" rows="6" placeholder="RequiresMountsFor=/opt/models" /></label>
          <label class="field"><span>[Service] 追加内容</span><textarea v-model="form.service_extra_text" rows="6" placeholder="Environment=CUDA_VISIBLE_DEVICES=0&#10;LimitNOFILE=1048576" /></label>
          <label class="field"><span>[Install] 追加内容</span><textarea v-model="form.install_extra_text" rows="6" placeholder="Alias=my-llama.service" /></label>
        </div>
      </PageSection>

      <PageSection title="Unit 文件预览" description="生成预览会保存当前基础配置与启动草稿，但不会写入 /etc/systemd/system。">
        <div class="inline-actions preview-actions">
          <button type="button" class="button secondary" :disabled="busy || !draft" @click="renderPreview"><IconRefresh :size="17" />生成预览</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="copyPreview"><IconCopy :size="17" />复制</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="downloadPreview"><IconDownload :size="17" />下载</button>
        </div>
        <pre class="code-block unit-preview">{{ preview || '导入 Profile 后点击“生成预览”。' }}</pre>
      </PageSection>

      <div v-if="selectedId" class="sticky-actions service-actions">
        <span v-if="selected?.applied_launch_config" class="applied-source">已应用来源：{{ appliedProfile?.name || '本地/历史模板' }}</span>
        <button type="button" class="button primary" :disabled="busy || !draft || !!selected?.archived_at" @click="deploy"><IconRocket :size="17" />应用并部署</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at" @click="action('start')"><IconPlayerPlay :size="17" />启动</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at" @click="action('stop')"><IconPlayerPause :size="17" />停止</button>
        <button type="button" class="button secondary" :disabled="!!selected?.archived_at" @click="action('restart')"><IconRefresh :size="17" />重启</button>
        <button type="button" class="button secondary" @click="showLogs">日志</button>
        <button v-if="!selected?.archived_at" type="button" class="button secondary" @click="archive"><IconArchive :size="17" />归档</button>
        <button v-else type="button" class="button secondary" @click="restore"><IconRestore :size="17" />恢复</button>
        <button type="button" class="button danger" @click="remove"><IconTrash :size="17" />彻底删除</button>
      </div>
      <pre v-if="logs" class="code-block">{{ logs }}</pre>
    </form>
  </div>
</template>
