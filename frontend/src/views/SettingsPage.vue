<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconDeviceFloppy, IconKey, IconPlus, IconTrash } from '@tabler/icons-vue'
import { settingsApi, authApi } from '../api'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import { setLocale, getLocale, type Locale } from '../i18n'
import type { AppSettings } from '../types'

const { t } = useI18n()
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
const currentLocale = ref<Locale>(getLocale())
function changeLocale(lang: Locale) {
  setLocale(lang)
  currentLocale.value = lang
}

async function load() {
  Object.assign(form, await settingsApi.get())
  loading.value = false
}
async function save() {
  saving.value = true
  try {
    Object.assign(form, await settingsApi.update(form))
    store.notify('success', t('settings.saved'))
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('settings.saveFailed'))
  } finally { saving.value = false }
}
async function rotateToken() {
  const value = newToken.value.trim()
  if (value.length < 16) {
    store.notify('error', t('settings.tokenHint'))
    return
  }
  rotating.value = true
  try {
    await authApi.rotate(value)
    newToken.value = ''
    store.notify('success', t('settings.tokenRotated'))
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('settings.rotateFailed'))
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
      {{ t('settings.publicWarning') }}
    </div>

    <PageSection :title="t('settings.language')" :description="t('settings.languageDesc')">
      <label class="field"><span>{{ t('settings.language') }}</span>
        <select :value="currentLocale" @change="changeLocale(($event.target as HTMLSelectElement).value as Locale)">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </label>
    </PageSection>

    <PageSection :title="t('settings.modelDirs')" :description="t('settings.modelDirsDesc')">
      <div class="path-list">
        <div v-for="(_, index) in form.model_roots" :key="index" class="path-row">
          <input v-model="form.model_roots[index]" required />
          <button type="button" class="icon-button danger" :aria-label="t('common.delete')" @click="removeRoot(index)"><IconTrash :size="17" /></button>
        </div>
        <button type="button" class="button secondary" @click="addRoot"><IconPlus :size="17" />{{ t('settings.addDir') }}</button>
      </div>
    </PageSection>

    <PageSection :title="t('settings.network')" :description="t('settings.networkDesc')">
      <div class="form-grid four-columns">
        <label class="field"><span>{{ t('settings.webHost') }}</span><input v-model="form.web_host" /><small>{{ t('settings.webHostDesc') }}</small></label>
        <label class="field"><span>{{ t('settings.webPort') }}</span><input v-model.number="form.web_port" type="number" /><small>{{ t('settings.webPortDesc') }}</small></label>
      </div>
    </PageSection>

    <PageSection :title="t('settings.tokenSection')" :description="t('settings.tokenSectionDesc')">
      <label class="field"><span>{{ t('settings.newToken') }}</span><input v-model="newToken" type="password" autocomplete="new-password" :placeholder="t('settings.tokenHint')" /></label>
      <button type="button" class="button secondary" :disabled="rotating || newToken.trim().length < 16" @click="rotateToken"><IconKey :size="17" />{{ t('settings.rotate') }}</button>
    </PageSection>

    <div class="sticky-actions">
      <button class="button primary" :disabled="saving"><IconDeviceFloppy :size="17" />{{ t('settings.saveSettings') }}</button>
    </div>
  </form>
</template>
