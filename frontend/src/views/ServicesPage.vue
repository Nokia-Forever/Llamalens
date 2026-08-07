<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  IconArchive, IconCopy, IconDeviceFloppy, IconDownload, IconPlayerPause, IconPlayerPlay,
  IconPlus, IconRefresh, IconRestore, IconRocket, IconTrash,
} from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { LlamaService, ServiceModel } from '../types'

const store = useAppStore()
const services = ref<LlamaService[]>([])
const selectedId = ref<string | null>(null)
const preview = ref('')
const busy = ref(false)
const logs = ref('')

const emptyForm = () => ({
  name: '', description: '', unit_name: '', server_bin: '/usr/local/bin/llama-server',
  service_user: 'root', service_group: 'root', working_directory: '/', host: '127.0.0.1', port: 8080,
  health_path: '/health', request_path: '/completion', mode: 'single' as 'single' | 'router',
  model_path: '', model_alias: '', models_dir: '', models_preset: '', models_max: 2,
  models_autoload: false, models: [] as ServiceModel[], custom_args_text: '', unit_extra_text: '',
  service_extra_text: '', install_extra_text: '',
})
const form = reactive(emptyForm())
const selected = computed(() => services.value.find((item) => item.id === selectedId.value) || null)

async function load(selectId?: string) {
  services.value = await api<LlamaService[]>('/services?include_archived=true&with_status=true')
  const target = services.value.find((item) => item.id === (selectId || selectedId.value))
  if (target) edit(target)
}

function reset() {
  selectedId.value = null
  Object.assign(form, emptyForm())
  preview.value = ''
  logs.value = ''
}

function edit(service: LlamaService) {
  selectedId.value = service.id
  Object.assign(form, {
    name: service.name, description: service.description, unit_name: service.unit_name,
    server_bin: service.server_bin, service_user: service.service_user, service_group: service.service_group,
    working_directory: service.working_directory, host: service.host, port: service.port,
    health_path: service.health_path, request_path: service.request_path, mode: service.mode,
    model_path: service.model_path, model_alias: service.model_alias, models_dir: service.models_dir,
    models_preset: service.models_preset, models_max: service.models_max,
    models_autoload: service.models_autoload, models: service.models.map((item) => ({ ...item })),
    custom_args_text: service.custom_args_text, unit_extra_text: service.unit_extra_text,
    service_extra_text: service.service_extra_text, install_extra_text: service.install_extra_text,
  })
  preview.value = service.rendered_unit
  logs.value = ''
}

function payload() {
  return {
    ...form,
    models: form.models.map(({ alias, model_path, display_name, enabled }) => ({ alias, model_path, display_name, enabled })),
  }
}

function addRouterModel() {
  form.models.push({ alias: '', model_path: '', display_name: '', enabled: true })
}

async function renderPreview() {
  try {
    const result = await api<{ content: string }>('/services/preview-unit', { method: 'POST', ...jsonBody(payload()) })
    preview.value = result.content
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '预览失败') }
}

async function save() {
  busy.value = true
  try {
    const saved = selectedId.value
      ? await api<LlamaService>(`/services/${selectedId.value}`, { method: 'PATCH', ...jsonBody(payload()) })
      : await api<LlamaService>('/services', { method: 'POST', ...jsonBody(payload()) })
    selectedId.value = saved.id
    preview.value = saved.rendered_unit
    store.notify('success', '服务配置已保存')
    await load(saved.id)
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '保存失败') }
  finally { busy.value = false }
}

async function deploy() {
  if (!selectedId.value) return store.notify('error', '请先保存服务')
  busy.value = true
  try {
    const result = await api<{ ok: boolean }>(`/services/${selectedId.value}/deploy`, { method: 'POST' })
    store.notify(result.ok ? 'success' : 'error', result.ok ? 'unit 已写入并执行 enable --now' : '部署失败，请查看状态')
    await load(selectedId.value)
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '部署失败') }
  finally { busy.value = false }
}

async function action(value: 'start' | 'stop' | 'restart') {
  if (!selectedId.value) return
  const result = await api<{ ok: boolean; stderr: string }>(`/services/${selectedId.value}/action`, {
    method: 'POST', ...jsonBody({ action: value }),
  })
  store.notify(result.ok ? 'success' : 'error', result.ok ? `${value} 已完成` : result.stderr || `${value} 失败`)
  await load(selectedId.value)
}

async function showLogs() {
  if (!selectedId.value) return
  const result = await api<{ stdout: string; stderr: string }>(`/services/${selectedId.value}/logs`)
  logs.value = result.stdout || result.stderr
}

async function archive() {
  if (!selectedId.value || !confirm('停止、禁用并归档这个服务？')) return
  await api(`/services/${selectedId.value}/archive`, { method: 'POST' })
  store.notify('success', '服务已归档')
  await load(selectedId.value)
}

async function restore() {
  if (!selectedId.value) return
  await api(`/services/${selectedId.value}/restore`, { method: 'POST' })
  store.notify('success', '服务文件已恢复，请按需重新部署')
  await load(selectedId.value)
}

async function remove() {
  if (!selectedId.value || !confirm('彻底停止、禁用并删除 unit 文件？模型文件不会删除。')) return
  await api(`/services/${selectedId.value}`, { method: 'DELETE' })
  store.notify('success', '服务及 unit 文件已删除')
  reset()
  await load()
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

onMounted(() => load())
</script>

<template>
  <div class="profile-workspace service-workspace">
    <aside class="profile-list-pane">
      <div class="pane-heading">
        <strong>Services</strong>
        <button class="icon-button" type="button" aria-label="新建服务" @click="reset"><IconPlus :size="18" /></button>
      </div>
      <button v-for="service in services" :key="service.id" class="profile-list-item" :class="{ active: selectedId === service.id }" @click="edit(service)">
        <span><strong>{{ service.name }}</strong><small>{{ service.unit_name }} · {{ service.host }}:{{ service.port }}</small></span>
        <StatusBadge :status="service.archived_at ? 'archived' : service.status?.ok ? 'active' : 'inactive'" />
      </button>
      <div v-if="!services.length" class="empty-state compact">还没有 Llama 服务。</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div><h2>{{ selectedId ? '编辑服务' : '创建服务' }}</h2><p>保存配置、预览 unit，确认后再部署到 systemd。</p></div>
        <button class="button primary" :disabled="busy"><IconDeviceFloppy :size="17" />保存</button>
      </div>

      <PageSection title="基础配置">
        <div class="form-grid two-columns">
          <label class="field"><span>服务名称</span><input v-model="form.name" required /></label>
          <label class="field"><span>Unit 名称</span><input v-model="form.unit_name" :disabled="!!selectedId" placeholder="自动生成 llamalens-*.service" /></label>
          <label class="field"><span>llama-server 路径</span><input v-model="form.server_bin" required /></label>
          <label class="field"><span>WorkingDirectory</span><input v-model="form.working_directory" required /></label>
          <label class="field"><span>User</span><input v-model="form.service_user" required /></label>
          <label class="field"><span>Group</span><input v-model="form.service_group" required /></label>
          <label class="field"><span>Host</span><input v-model="form.host" required /></label>
          <label class="field"><span>Port</span><input v-model.number="form.port" type="number" min="1" max="65535" required /></label>
        </div>
      </PageSection>

      <PageSection title="模型启动方式">
        <div class="form-grid two-columns">
          <label class="field"><span>模式</span><select v-model="form.mode"><option value="single">单模型</option><option value="router">Router 多模型</option></select></label>
          <label class="field"><span>额外 llama-server 参数</span><input v-model="form.custom_args_text" placeholder="--ctx-size 8192 --gpu-layers all" /></label>
        </div>
        <div v-if="form.mode === 'single'" class="form-grid two-columns">
          <label class="field"><span>GGUF 路径</span><input v-model="form.model_path" required /></label>
          <label class="field"><span>模型 Alias</span><input v-model="form.model_alias" required /></label>
        </div>
        <div v-else class="page-stack compact-stack">
          <div class="form-grid two-columns">
            <label class="field"><span>--models-dir</span><input v-model="form.models_dir" required /></label>
            <label class="field"><span>--models-preset</span><input v-model="form.models_preset" /></label>
            <label class="field"><span>--models-max</span><input v-model.number="form.models_max" type="number" min="0" /></label>
            <label class="check-field"><input v-model="form.models_autoload" type="checkbox" /><span>--models-autoload</span></label>
          </div>
          <div class="pane-heading"><strong>可测试模型 Alias</strong><button type="button" class="button secondary" @click="addRouterModel"><IconPlus :size="16" />添加</button></div>
          <div v-for="(model, index) in form.models" :key="index" class="form-grid router-model-row">
            <input v-model="model.alias" placeholder="必填 alias" required />
            <input v-model="model.display_name" placeholder="显示名称" />
            <input v-model="model.model_path" placeholder="模型路径，可选" />
            <button type="button" class="icon-button danger" @click="form.models.splice(index, 1)"><IconTrash :size="16" /></button>
          </div>
        </div>
      </PageSection>

      <PageSection title="Systemd 自定义参数" description="每行一个 systemd 指令；内容会追加到对应 section，并禁止重复 ExecStart。">
        <div class="unit-section-grid">
          <label class="field"><span>[Unit] 追加内容</span><textarea v-model="form.unit_extra_text" rows="6" placeholder="RequiresMountsFor=/opt/models" /></label>
          <label class="field"><span>[Service] 追加内容</span><textarea v-model="form.service_extra_text" rows="6" placeholder="Environment=CUDA_VISIBLE_DEVICES=0&#10;LimitNOFILE=1048576" /></label>
          <label class="field"><span>[Install] 追加内容</span><textarea v-model="form.install_extra_text" rows="6" placeholder="Alias=my-llama.service" /></label>
        </div>
      </PageSection>

      <PageSection title="Unit 文件预览" description="预览不会写入系统；部署使用服务端生成并保存的同一份内容。">
        <div class="inline-actions preview-actions">
          <button type="button" class="button secondary" @click="renderPreview"><IconRefresh :size="17" />生成预览</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="copyPreview"><IconCopy :size="17" />复制</button>
          <button type="button" class="button secondary" :disabled="!preview" @click="downloadPreview"><IconDownload :size="17" />下载</button>
        </div>
        <pre class="code-block unit-preview">{{ preview || '填写配置后点击“生成预览”。' }}</pre>
      </PageSection>

      <div v-if="selectedId" class="sticky-actions service-actions">
        <button type="button" class="button primary" :disabled="busy || !!selected?.archived_at" @click="deploy"><IconRocket :size="17" />部署 enable --now</button>
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
