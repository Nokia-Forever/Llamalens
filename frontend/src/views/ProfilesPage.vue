<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { IconDeviceFloppy, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-vue'
import { useI18n } from 'vue-i18n'
import { profilesApi, modelsApi, argumentsApi } from '../api'
import LaunchConfigEditor from '../components/LaunchConfigEditor.vue'
import PageSection from '../components/PageSection.vue'
import { useAppStore } from '../stores/app'
import { useBusy } from '../composables/useBusy'
import { cloneConfig } from '../utils'
import type { CatalogArgument, LaunchConfig, ModelFile, Profile } from '../types'

type ProfileForm = LaunchConfig & { name: string }

const store = useAppStore()
const { t } = useI18n()
const profiles = ref<Profile[]>([])
const models = ref<ModelFile[]>([])
const catalog = ref<CatalogArgument[]>([])
const selectedId = ref<string | null>(null)
const { run: runBusy, isBusy } = useBusy()

function emptyConfig(): LaunchConfig {
  return {
    mode: 'single', model_path: models.value[0]?.path || '', model_alias: '', models_dir: '',
    models_preset: '', models_max: 2, models_autoload: false, models: [], catalog_args: [],
    custom_args_text: '', labels: {},
  }
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
  if (profile.mode === 'single') return t('profiles.singleSummary', { alias: profile.model_alias || t('profiles.aliasUnset') })
  return t('profiles.routerSummary', { count: profile.models.filter((item) => item.enabled).length })
}

async function load(selectId?: string) {
  const [profilesPage, modelsPage, catalogPage] = await Promise.all([
    profilesApi.list(),
    modelsApi.list(),
    argumentsApi.list({ limit: 1000 }),
  ])
  profiles.value = profilesPage.items
  models.value = modelsPage.items
  catalog.value = catalogPage
  const target = profiles.value.find((profile) => profile.id === (selectId || selectedId.value))
  if (target) edit(target)
  else if (!selectedId.value && profiles.value.length) edit(profiles.value[0])
  else if (!profiles.value.length) reset()
}

async function save() {
  await runBusy('profile.save', async () => {
    try {
      const saved = selectedId.value
        ? await profilesApi.update(selectedId.value, payload())
        : await profilesApi.create(payload())
      selectedId.value = saved.id
      store.notify('success', t('profiles.savedIndependent'))
      await load(saved.id)
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('profiles.saveFailed'))
    }
  })
}

async function remove() {
  if (!selectedId.value || !confirm(t('profiles.deleteTemplateConfirm'))) return
  const id = selectedId.value
  await runBusy('profile.delete', async () => {
    try {
      await profilesApi.delete(id)
      store.notify('success', t('profiles.deleted'))
      reset()
      await load()
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('profiles.deleteFailed'))
    }
  })
}

async function refreshCatalog() {
  await runBusy('profile.refreshCatalog', async () => {
    try {
      const result = await argumentsApi.refresh()
      if (!result.ok) throw new Error(result.error || t('profiles.refreshFailed'))
      catalog.value = await argumentsApi.list({ limit: 1000 })
      store.notify('success', t('profiles.refreshSuccess', { count: result.count }))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('profiles.refreshCatalogFailed'))
    }
  })
}

onMounted(() => load())
</script>

<template>
  <div class="profile-workspace">
    <aside class="profile-list-pane">
      <div class="pane-heading">
        <strong>Profiles</strong>
        <button class="icon-button" type="button" :aria-label="t('profiles.newTemplate')" @click="reset"><IconPlus :size="18" /></button>
      </div>
      <button v-for="profile in profiles" :key="profile.id" class="profile-list-item" :class="{ active: selectedId === profile.id }" @click="edit(profile)">
        <span><strong>{{ profile.name }}</strong><small>{{ summary(profile) }}</small></span>
      </button>
      <div v-if="!profiles.length" class="empty-state compact">{{ t('profiles.emptyTemplates') }}</div>
    </aside>

    <form class="profile-editor" @submit.prevent="save">
      <div class="editor-heading">
        <div>
          <h2>{{ selectedId ? t('profiles.editTemplate') : t('profiles.newTemplate') }}</h2>
          <p>{{ t('profiles.templateDescription') }}</p>
        </div>
        <div class="inline-actions">
          <button v-if="selectedId" type="button" class="icon-button danger" :aria-label="t('common.delete')" :disabled="isBusy('profile.delete')" @click="remove"><IconTrash :size="18" /></button>
          <button class="button primary" :disabled="isBusy('profile.save')"><IconDeviceFloppy :size="17" />{{ t('profiles.saveTemplate') }}</button>
        </div>
      </div>

      <PageSection :title="t('profiles.templateInfo')" :description="t('profiles.templateInfoDesc')">
        <label class="field profile-name-field"><span>{{ t('profiles.name') }}</span><input v-model.trim="form.name" required :placeholder="t('profiles.namePlaceholder')" /></label>
      </PageSection>

      <PageSection :title="t('profiles.modelAndArgs')">
        <div class="inline-actions catalog-toolbar">
          <span class="muted-copy">{{ t('profiles.catalogHint') }}</span>
          <button type="button" class="button secondary" :disabled="isBusy('profile.refreshCatalog')" @click="refreshCatalog"><IconRefresh :size="17" />{{ t('profiles.refreshCatalog') }}</button>
        </div>
        <LaunchConfigEditor :config="form" :models="models" :catalog="catalog" />
      </PageSection>

      <PageSection v-if="selected" :title="t('profiles.savedArgv')" :description="t('profiles.savedArgvDesc')">
        <pre class="code-block compact-code">{{ selected.final_argv.join(' ') }}</pre>
        <div v-if="selected.warnings.length" class="risk-banner neutral">{{ selected.warnings.join('；') }}</div>
      </PageSection>
    </form>
  </div>
</template>
