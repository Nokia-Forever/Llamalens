<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { IconDeviceFloppy, IconPlayerPlay, IconPlus, IconRefresh, IconSearch, IconTrash, IconX } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { CatalogArgument, LlamaService, ModelFile, Profile, SelectedArgument } from '../types'

const store = useAppStore()
const profiles = ref<Profile[]>([])
const services = ref<LlamaService[]>([])
const models = ref<ModelFile[]>([])
const catalog = ref<CatalogArgument[]>([])
const selectedId = ref<string | null>(null)
const search = ref('')
const saving = ref(false)
const switching = ref(false)
const form = reactive({ service_id: null as string | null, model_alias: '', name: '', model_path: '', catalog_args: [] as SelectedArgument[], custom_args_text: '', labels: {} as Record<string, string> })

const selected = computed(() => profiles.value.find((profile) => profile.id === selectedId.value) || null)
const selectedService = computed(() => services.value.find((service) => service.id === form.service_id) || null)
const availableAliases = computed(() => selectedService.value?.models.filter((item) => item.enabled) || [])
const filteredCatalog = computed(() => {
  const needle = search.value.trim().toLowerCase().replace(/(-{1,2})\s+/g, '$1')
  if (needle === '-') {
    return catalog.value.filter((item) => item.aliases.some(isShortAlias)).slice(0, 100)
  }
  return catalog.value.filter((item) => `${item.key} ${item.aliases.join(' ')} ${item.description} ${item.category}`.toLowerCase().includes(needle)).slice(0, 100)
})
const preview = computed(() => {
  const base = ['llama-server', '--model', form.model_path || '<model>', '--host', '<configured-host>', '--port', '<configured-port>']
  for (const item of form.catalog_args) { base.push(item.flag); if (item.value) base.push(item.value) }
  for (const line of form.custom_args_text.split('\n').map((line) => line.trim()).filter(Boolean)) base.push(...line.split(/\s+/))
  return base.join(' ')
})
const duplicateFlags = computed(() => {
  const flags = form.catalog_args.map((item) => item.flag)
  const customFlags = form.custom_args_text.split(/\s+/).filter((item) => item.startsWith('-'))
  const counts = [...flags, ...customFlags].reduce<Record<string, number>>((all, flag) => {
    all[flag] = (all[flag] || 0) + 1
    return all
  }, {})
  return Object.entries(counts).filter(([, count]) => count > 1).map(([flag]) => flag)
})

async function load() {
  ;[profiles.value, models.value, catalog.value, services.value] = await Promise.all([
    api<Profile[]>('/profiles'), api<ModelFile[]>('/models'), api<CatalogArgument[]>('/arguments?limit=1000'), api<LlamaService[]>('/services'),
  ])
  if (!selectedId.value && profiles.value.length) edit(profiles.value[0])
}
function reset() {
  selectedId.value = null
  Object.assign(form, { service_id: services.value[0]?.id || null, model_alias: services.value[0]?.models[0]?.alias || '', name: '', model_path: models.value[0]?.path || '', catalog_args: [], custom_args_text: '', labels: {} })
}
function edit(profile: Profile) {
  selectedId.value = profile.id
  Object.assign(form, {
    service_id: profile.service_id, model_alias: profile.model_alias, name: profile.name, model_path: profile.model_path,
    catalog_args: profile.catalog_args.map((item) => ({ ...item })), custom_args_text: profile.custom_args_text,
    labels: { ...profile.labels },
  })
}
function addArgument(item: CatalogArgument) {
  const flag = item.aliases.find((alias) => alias.startsWith('--')) || item.key
  form.catalog_args.push({ flag, value: '' })
}
function argumentAliases(item: CatalogArgument) {
  return item.aliases.length ? item.aliases : [item.key]
}
function isShortAlias(alias: string) {
  return alias.startsWith('-') && !alias.startsWith('--')
}
function removeArgument(index: number) { form.catalog_args.splice(index, 1) }
async function save() {
  saving.value = true
  const payload = { ...form }
  try {
    if (selectedId.value) await api(`/profiles/${selectedId.value}`, { method: 'PUT', ...jsonBody(payload) })
    else await api('/profiles', { method: 'POST', ...jsonBody(payload) })
    store.notify('success', 'Profile 已保存')
    await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '保存失败') }
  finally { saving.value = false }
}
async function activate() {
  if (!selectedId.value) return
  switching.value = true
  try {
    const job = await api<{ id: string }>(`/profiles/${selectedId.value}/activate`, { method: 'POST' })
    store.notify('info', `切换任务已创建: ${job.id.slice(0, 8)}`)
    for (;;) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
      const state = await api<{ status: string; message: string }>(`/profiles/switch-jobs/${job.id}`)
      if (state.status === 'succeeded') {
        store.notify('success', state.message)
        await load()
        break
      }
      if (state.status === 'failed') throw new Error(state.message)
    }
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '切换失败') }
  finally { switching.value = false }
}
async function remove() {
  if (!selectedId.value || selected.value?.is_active || !confirm('删除这个 Profile？')) return
  try {
    await api(`/profiles/${selectedId.value}`, { method: 'DELETE' })
    reset(); await load()
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '删除失败') }
}
async function refreshCatalog() {
  try {
    const result = await api<{ ok: boolean; count: number; error: string | null }>('/arguments/refresh', { method: 'POST' })
    if (!result.ok) throw new Error(result.error || '刷新失败')
    catalog.value = await api<CatalogArgument[]>('/arguments?limit=1000')
    store.notify('success', `已从 llama-server --help 读取 ${result.count} 个参数`)
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '刷新参数目录失败') }
}
onMounted(load)
</script>

<template>
  <div class="profile-workspace">
    <aside class="profile-list-pane">
      <div class="pane-heading"><strong>Profiles</strong><button class="icon-button" aria-label="新建 Profile" @click="reset"><IconPlus :size="18" /></button></div>
      <button v-for="profile in profiles" :key="profile.id" class="profile-list-item" :class="{ active: selectedId === profile.id }" @click="edit(profile)">
        <span><strong>{{ profile.name }}</strong><small>{{ profile.model_path.split(/[\\/]/).pop() }}</small></span>
        <StatusBadge v-if="profile.is_active" status="active" label="Active" />
      </button>
      <div v-if="!profiles.length" class="empty-state compact">还没有 Profile。</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div><h2>{{ selectedId ? '编辑 Profile' : '新建 Profile' }}</h2><p>只选择模型即可保存，其余参数按需添加。</p></div>
        <div class="inline-actions">
          <button v-if="selectedId && !selected?.is_active" type="button" class="icon-button danger" aria-label="删除" @click="remove"><IconTrash :size="18" /></button>
          <button v-if="selectedId" type="button" class="button secondary" :disabled="switching" @click="activate"><IconPlayerPlay :size="17" />激活</button>
          <button class="button primary" :disabled="saving"><IconDeviceFloppy :size="17" />保存</button>
        </div>
      </div>

      <PageSection title="必填信息">
        <div class="form-grid two-columns">
          <label class="field"><span>目标 Service</span><select v-model="form.service_id" required><option :value="null" disabled>选择 Service</option><option v-for="service in services" :key="service.id" :value="service.id">{{ service.name }} · {{ service.host }}:{{ service.port }}</option></select></label>
          <label class="field"><span>模型 Alias</span><select v-model="form.model_alias" required><option value="" disabled>选择 Alias</option><option v-for="model in availableAliases" :key="model.alias" :value="model.alias">{{ model.display_name || model.alias }}</option></select></label>
          <label class="field"><span>Profile 名称</span><input v-model="form.name" required /></label>
          <label class="field"><span>模型</span><select v-model="form.model_path" required><option value="" disabled>选择 GGUF</option><option v-for="model in models" :key="model.id" :value="model.path">{{ model.name }}</option></select></label>
        </div>
      </PageSection>

      <PageSection title="已选参数" description="参数按这里的顺序进入最终 argv。--host 和 --port 已由设置页自动加入，一般不要在这里重复配置。">
        <div v-if="duplicateFlags.length" class="risk-banner">检测到重复参数: {{ duplicateFlags.join(', ') }}。不会阻止保存，后出现的值排在 argv 后面。</div>
        <div v-if="!form.catalog_args.length" class="empty-state compact">从右侧参数目录添加，或者直接使用下方自定义参数。</div>
        <div class="selected-args">
          <div v-for="(item, index) in form.catalog_args" :key="`${item.flag}-${index}`" class="arg-edit-row">
            <input v-model="item.flag" class="flag-input" />
            <input v-model="item.value" placeholder="值，可留空" />
            <button type="button" class="icon-button" aria-label="移除参数" @click="removeArgument(index)"><IconX :size="17" /></button>
          </div>
        </div>
      </PageSection>

      <div class="profile-lower-grid">
        <PageSection title="参数目录" description="目录会从目标机 llama-server --help 刷新。">
          <button type="button" class="button secondary catalog-refresh" @click="refreshCatalog"><IconRefresh :size="17" />刷新本机参数</button>
          <label class="search-box full"><IconSearch :size="17" /><input v-model="search" placeholder="搜索 parallel、batch、GPU 或 flag" /></label>
          <div class="argument-catalog">
            <div v-if="!filteredCatalog.length" class="empty-state compact catalog-empty">
              {{ catalog.length ? '没有匹配的参数，请尝试清空搜索条件。' : '参数目录为空，请先刷新本机参数并检查 llama-server 路径。' }}
            </div>
            <button v-for="item in filteredCatalog" :key="item.id" type="button" class="catalog-row" @click="addArgument(item)">
              <span>
                <span class="catalog-aliases">
                  <code
                    v-for="alias in argumentAliases(item)"
                    :key="alias"
                    :class="{ 'short-alias': isShortAlias(alias) }"
                  >{{ alias }}</code>
                </span>
                <small>{{ item.description || item.value_hint }}</small>
              </span>
              <em>{{ item.category }}</em>
            </button>
          </div>
        </PageSection>
        <PageSection title="自定义参数" description="每行一个参数片段，始终追加在最后。">
          <textarea v-model="form.custom_args_text" class="custom-args" spellcheck="false" placeholder="-np 1&#10;--cache-type-k q8_0" />
          <div class="argv-preview"><strong>输入顺序预览</strong><code>{{ preview }}</code><small>保存时以后端 POSIX shlex 解析结果为准。</small></div>
        </PageSection>
      </div>
    </form>
  </div>
</template>
