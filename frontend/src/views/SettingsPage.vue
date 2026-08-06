<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { IconDeviceFloppy, IconPlugConnected, IconPlus, IconTrash } from '@tabler/icons-vue'
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
const probe = ref<Record<string, unknown> | null>(null)
const publicWarning = computed(() => form.web_host === '0.0.0.0' || form.web_host === '::')

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
async function testConnection() {
  try {
    probe.value = await api<Record<string, unknown>>('/settings/probe')
    store.notify('info', '探测完成，请查看结果')
  } catch (error) { store.notify('error', error instanceof Error ? error.message : '探测失败') }
}
function addRoot() { form.model_roots.push('') }
function removeRoot(index: number) { form.model_roots.splice(index, 1) }
onMounted(load)
</script>

<template>
  <div v-if="loading" class="skeleton-stack"><div /><div /></div>
  <form v-else class="settings-form" @submit.prevent="save">
    <div v-if="publicWarning" class="risk-banner">
      当前 Web 将监听所有网卡，V1 没有登录验证。任何能访问端口的人都可能操作模型和 service。
    </div>

    <PageSection title="llama.cpp 服务" description="LlamaLens 只记录和控制用户已经创建的 systemd service。">
      <div class="form-grid two-columns">
        <label class="field"><span>Service 名称</span><input v-model="form.llama_service_name" required /><small>例如 llama-server.service</small></label>
        <label class="field"><span>Unit 文件位置</span><input v-model="form.llama_service_file" required /></label>
        <label class="field"><span>Systemd 范围</span><select v-model="form.service_scope"><option value="system">system</option><option value="user">user</option></select></label>
        <label class="field"><span>控制命令</span><input v-model="form.service_control_command" :disabled="form.service_scope === 'user'" /><small>程序不保存 sudo 密码。</small></label>
        <label class="field"><span>llama-server 路径</span><input v-model="form.llama_server_bin" required /></label>
        <label class="field"><span>活动 Profile 文件</span><input v-model="form.active_profile_path" required /></label>
      </div>
    </PageSection>

    <PageSection title="模型目录" description="扫描和下载都限制在这些目录中。">
      <div class="path-list">
        <div v-for="(_, index) in form.model_roots" :key="index" class="path-row">
          <input v-model="form.model_roots[index]" required />
          <button type="button" class="icon-button danger" aria-label="删除目录" @click="removeRoot(index)"><IconTrash :size="17" /></button>
        </div>
        <button type="button" class="button secondary" @click="addRoot"><IconPlus :size="17" />添加目录</button>
      </div>
    </PageSection>

    <PageSection title="网络" description="Web 和 llama-server 地址分别配置。Web Host/Port 保存后需要重启 LlamaLens service 才会生效。">
      <div class="form-grid four-columns">
        <label class="field"><span>Web Host</span><input v-model="form.web_host" /></label>
        <label class="field"><span>Web Port</span><input v-model.number="form.web_port" type="number" /></label>
        <label class="field"><span>Llama Host</span><input v-model="form.llama_host" /></label>
        <label class="field"><span>Llama Port</span><input v-model.number="form.llama_port" type="number" /></label>
        <label class="field"><span>Health Path</span><input v-model="form.health_path" /></label>
        <label class="field"><span>Request Path</span><input v-model="form.request_path" /></label>
      </div>
    </PageSection>

    <div class="sticky-actions">
      <button type="button" class="button secondary" @click="testConnection"><IconPlugConnected :size="17" />测试连接</button>
      <button class="button primary" :disabled="saving"><IconDeviceFloppy :size="17" />保存设置</button>
    </div>
    <pre v-if="probe" class="code-block">{{ JSON.stringify(probe, null, 2) }}</pre>
  </form>
</template>
