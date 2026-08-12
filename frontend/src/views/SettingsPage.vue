<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { IconDeviceFloppy, IconKey, IconPlus, IconTrash } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import type { AppSettings } from '../types'

const store = useAppStore()
const form = reactive<AppSettings>({
  llama_server_bin: '', llama_service_name: '', llama_service_file: '', service_scope: 'system',
  service_control_command: 'sudo -n systemctl', active_profile_path: '', model_roots: [], web_host: '127.0.0.1',
  web_port: 3000, llama_host: '127.0.0.1', llama_port: 8080, health_path: '/health', request_path: '/completion',
  download_timeout_seconds: 3600,
})
const loading = ref(true)
const saving = ref(false)
const publicWarning = computed(() => form.web_host === '0.0.0.0' || form.web_host === '::')
const newToken = ref('')
const rotating = ref(false)

async function load() {
  Object.assign(form, await api<AppSettings>('/settings'))
  loading.value = false
}
async function save() {
  saving.value = true
  try {
    Object.assign(form, await api<AppSettings>('/settings', { method: 'PUT', ...jsonBody(form) }))
    store.notify('success', '设置已保存')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '保存失败')
  } finally { saving.value = false }
}
async function rotateToken() {
  const value = newToken.value.trim()
  if (value.length < 16) {
    store.notify('error', '令牌至少 16 个字符')
    return
  }
  rotating.value = true
  try {
    await api('/auth/rotate', { method: 'POST', ...jsonBody({ new_token: value }) })
    newToken.value = ''
    store.notify('success', '令牌已轮换，请使用新令牌重新登录')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '轮换失败')
  } finally { rotating.value = false }
}
function addRoot() { form.model_roots.push('') }
function removeRoot(index: number) { form.model_roots.splice(index, 1) }
onMounted(load)
</script>

<template>
  <div v-if="loading" class="skeleton-stack"><div /><div /></div>
  <form v-else class="settings-form" @submit.prevent="save">
    <div v-if="publicWarning" class="risk-banner">
      当前 Web 将监听所有网卡。请配置 API 令牌（见下方“访问令牌”），否则任何能访问端口的人都可操作模型和 service。
    </div>

    <PageSection title="模型目录" description="扫描和下载都限制在这些目录中。">
      <div class="path-list">
        <div v-for="(_, index) in form.model_roots" :key="index" class="path-row">
          <input v-model="form.model_roots[index]" required />
          <button type="button" class="icon-button danger" aria-label="删除目录" @click="removeRoot(index)"><IconTrash :size="17" /></button>
        </div>
        <button type="button" class="button secondary" @click="addRoot"><IconPlus :size="17" />添加目录</button>
      </div>
    </PageSection>

    <PageSection title="管理页面网络" description="每个 llama-server 的 host、port 和 API 路径请在 Services 页面独立设置。">
      <div class="form-grid four-columns">
        <label class="field"><span>Web Host</span><input v-model="form.web_host" /><small>LlamaLens 管理页面的监听地址。</small></label>
        <label class="field"><span>Web Port</span><input v-model.number="form.web_port" type="number" /><small>LlamaLens 管理页面的端口；保存后需重启 LlamaLens。</small></label>
      </div>
    </PageSection>

    <PageSection title="访问令牌" description="轮换后旧令牌立即失效，远程会话需用新令牌重新登录。loopback 默认免认证，可用 LLAMALENS_REQUIRE_AUTH=1 强制。">
      <label class="field"><span>新令牌</span><input v-model="newToken" type="password" autocomplete="new-password" placeholder="至少 16 个字符" /></label>
      <button type="button" class="button secondary" :disabled="rotating || newToken.trim().length < 16" @click="rotateToken"><IconKey :size="17" />轮换令牌</button>
    </PageSection>

    <div class="sticky-actions">
      <button class="button primary" :disabled="saving"><IconDeviceFloppy :size="17" />保存设置</button>
    </div>
  </form>
</template>
