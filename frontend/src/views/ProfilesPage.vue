<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { IconDeviceFloppy, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import LaunchConfigEditor from '../components/LaunchConfigEditor.vue'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import type { CatalogArgument, LaunchConfig, ModelFile, Profile } from '../types'

type ProfileForm = LaunchConfig & { name: string }

const store = useAppStore()
const profiles = ref<Profile[]>([])
const models = ref<ModelFile[]>([])
const catalog = ref<CatalogArgument[]>([])
const selectedId = ref<string | null>(null)
const saving = ref(false)

function emptyConfig(): LaunchConfig {
  return {
    mode: 'single', model_path: models.value[0]?.path || '', model_alias: '', models_dir: '',
    models_preset: '', models_max: 2, models_autoload: false, models: [], catalog_args: [],
    custom_args_text: '', labels: {},
  }
}

function cloneConfig(source: LaunchConfig): LaunchConfig {
  return JSON.parse(JSON.stringify(source)) as LaunchConfig
}

const form = reactive<ProfileForm>({ name: '', ...emptyConfig() })
const selected = computed(() => profiles.value.find((profile) => profile.id === selectedId.value) || null)

function profileConfig(profile: Profile): LaunchConfig {
  return cloneConfig({
    mode: profile.mode, model_path: profile.model_path, model_alias: profile.model_alias,
    models_dir: profile.models_dir, models_preset: profile.models_preset, models_max: profile.models_max,
    models_autoload: profile.models_autoload, models: profile.models, catalog_args: profile.catalog_args,
    custom_args_text: profile.custom_args_text, labels: profile.labels,
  })
}

function payload() {
  return {
    name: form.name, mode: form.mode, model_path: form.model_path, model_alias: form.model_alias,
    models_dir: form.models_dir, models_preset: form.models_preset, models_max: form.models_max,
    models_autoload: form.models_autoload, models: form.models, catalog_args: form.catalog_args,
    custom_args_text: form.custom_args_text, labels: form.labels,
  }
}

function reset() {
  selectedId.value = null
  Object.assign(form, { name: '', ...emptyConfig() })
}

function edit(profile: Profile) {
  selectedId.value = profile.id
  Object.assign(form, { name: profile.name, ...profileConfig(profile) })
}

function summary(profile: Profile) {
  if (profile.mode === 'single') return `单模型 · ${profile.model_alias || '未设置 alias'}`
  return `Router · ${profile.models.filter((item) => item.enabled).length} 个模型`
}

async function load(selectId?: string) {
  ;[profiles.value, models.value, catalog.value] = await Promise.all([
    api<Profile[]>('/profiles'), api<ModelFile[]>('/models'), api<CatalogArgument[]>('/arguments?limit=1000'),
  ])
  const target = profiles.value.find((profile) => profile.id === (selectId || selectedId.value))
  if (target) edit(target)
  else if (!selectedId.value && profiles.value.length) edit(profiles.value[0])
  else if (!profiles.value.length) reset()
}

async function save() {
  saving.value = true
  try {
    const saved = selectedId.value
      ? await api<Profile>(`/profiles/${selectedId.value}`, { method: 'PUT', ...jsonBody(payload()) })
      : await api<Profile>('/profiles', { method: 'POST', ...jsonBody(payload()) })
    selectedId.value = saved.id
    store.notify('success', 'Profile 模板已保存；已导入的 Service 不会被修改')
    await load(saved.id)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!selectedId.value || !confirm('删除这个 Profile 模板？已导入 Service 的本地副本不会被删除。')) return
  try {
    await api(`/profiles/${selectedId.value}`, { method: 'DELETE' })
    reset()
    await load()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '删除失败')
  }
}

async function refreshCatalog() {
  try {
    const result = await api<{ ok: boolean; count: number; error: string | null }>('/arguments/refresh', { method: 'POST' })
    if (!result.ok) throw new Error(result.error || '刷新失败')
    catalog.value = await api<CatalogArgument[]>('/arguments?limit=1000')
    store.notify('success', `已从 llama-server --help 读取 ${result.count} 个参数`)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '刷新参数目录失败')
  }
}

onMounted(() => load())
</script>

<template>
  <div class="profile-workspace">
    <aside class="profile-list-pane">
      <div class="pane-heading">
        <strong>Profiles</strong>
        <button class="icon-button" type="button" aria-label="新建 Profile" @click="reset"><IconPlus :size="18" /></button>
      </div>
      <button v-for="profile in profiles" :key="profile.id" class="profile-list-item" :class="{ active: selectedId === profile.id }" @click="edit(profile)">
        <span><strong>{{ profile.name }}</strong><small>{{ summary(profile) }}</small></span>
      </button>
      <div v-if="!profiles.length" class="empty-state compact">还没有 Profile 模板。</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div>
          <h2>{{ selectedId ? '编辑 Profile 模板' : '新建 Profile 模板' }}</h2>
          <p>Profile 只保存启动参数模板，不绑定 Service，也不会直接重启任何服务。</p>
        </div>
        <div class="inline-actions">
          <button v-if="selectedId" type="button" class="icon-button danger" aria-label="删除" @click="remove"><IconTrash :size="18" /></button>
          <button class="button primary" :disabled="saving"><IconDeviceFloppy :size="17" />保存模板</button>
        </div>
      </div>

      <PageSection title="模板信息" description="一个 Profile 可以导入到任意多个 Service；导入后各 Service 独立修改。">
        <label class="field profile-name-field"><span>Profile 名称</span><input v-model.trim="form.name" required placeholder="例如 Qwen 32B · GPU0" /></label>
      </PageSection>

      <PageSection title="模型与 llama 参数">
        <div class="inline-actions catalog-toolbar">
          <span class="muted-copy">参数目录供下方搜索选择。</span>
          <button type="button" class="button secondary" @click="refreshCatalog"><IconRefresh :size="17" />刷新本机参数</button>
        </div>
        <LaunchConfigEditor :config="form" :models="models" :catalog="catalog" />
      </PageSection>

      <PageSection v-if="selected" title="上次保存的 argv" description="Service 导入模板后会使用自己的 server 路径、Host 和 Port 重新生成 argv。">
        <pre class="code-block compact-code">{{ selected.final_argv.join(' ') }}</pre>
        <div v-if="selected.warnings.length" class="risk-banner neutral">{{ selected.warnings.join('；') }}</div>
      </PageSection>
    </form>
  </div>
</template>
