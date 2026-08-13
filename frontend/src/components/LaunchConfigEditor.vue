<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPlus, IconSearch, IconTrash, IconX } from '@tabler/icons-vue'
import type { CatalogArgument, LaunchConfig, ModelFile } from '../types'

const props = defineProps<{ config: LaunchConfig; models: ModelFile[]; catalog: CatalogArgument[] }>()
const { t } = useI18n()
const search = ref('')
const modelListId = `launch-models-${Math.random().toString(36).slice(2)}`

const filteredCatalog = computed(() => {
  const needle = search.value.trim().toLowerCase().replace(/(-{1,2})\s+/g, '$1')
  return props.catalog
    .filter((item) => `${item.key} ${item.aliases.join(' ')} ${item.description} ${item.category}`.toLowerCase().includes(needle))
    .slice(0, 100)
})

function addRouterModel() {
  props.config.models.push({ alias: '', model_path: '', display_name: '', enabled: true })
}

function addArgument(item: CatalogArgument) {
  const flag = item.aliases.find((alias) => alias.startsWith('--')) || item.aliases[0] || item.key
  props.config.catalog_args.push({ flag, value: '' })
}
</script>

<template>
  <div class="page-stack compact-stack">
    <datalist :id="modelListId">
      <option v-for="model in models" :key="model.id" :value="model.path">{{ model.name }}</option>
    </datalist>

    <div class="form-grid two-columns">
      <label class="field">
        <span>{{ t('launchEditor.mode') }}</span>
        <select v-model="config.mode">
          <option value="single">{{ t('launchEditor.single') }}</option>
          <option value="router">{{ t('launchEditor.router') }}</option>
        </select>
      </label>
      <label v-if="config.mode === 'single'" class="field">
        <span>{{ t('launchEditor.modelAlias') }}</span>
        <input v-model.trim="config.model_alias" required :placeholder="t('launchEditor.aliasPlaceholder')" />
      </label>
    </div>

    <div v-if="config.mode === 'single'" class="form-grid two-columns">
      <label class="field">
        <span>{{ t('launchEditor.modelPath') }}</span>
        <input v-model.trim="config.model_path" :list="modelListId" required placeholder="/srv/models/model.gguf" />
        <small>{{ t('launchEditor.modelPathHint') }}</small>
      </label>
    </div>

    <template v-else>
      <div class="form-grid two-columns">
        <label class="field"><span>--models-dir</span><input v-model.trim="config.models_dir" required placeholder="/srv/models" /></label>
        <label class="field"><span>--models-preset</span><input v-model.trim="config.models_preset" :placeholder="t('launchEditor.presetPlaceholder')" /></label>
        <label class="field"><span>--models-max</span><input v-model.number="config.models_max" type="number" min="0" /></label>
        <label class="check-field"><input v-model="config.models_autoload" type="checkbox" /><span>{{ t('launchEditor.enableAutoload') }}</span></label>
      </div>

      <div class="pane-heading">
        <div><strong>{{ t('launchEditor.routerAliases') }}</strong><small>{{ t('launchEditor.routerAliasesHint') }}</small></div>
        <button type="button" class="button secondary" @click="addRouterModel"><IconPlus :size="16" />{{ t('launchEditor.addModel') }}</button>
      </div>
      <div v-if="!config.models.length" class="empty-state compact">{{ t('launchEditor.modelRequired') }}</div>
      <div v-for="(model, index) in config.models" :key="index" class="form-grid router-model-row">
        <input v-model.trim="model.alias" :placeholder="t('launchEditor.requiredAlias')" required />
        <input v-model="model.display_name" :placeholder="t('launchEditor.displayName')" />
        <input v-model.trim="model.model_path" :list="modelListId" :placeholder="t('launchEditor.routerModelPath')" />
        <label class="check-field compact-check"><input v-model="model.enabled" type="checkbox" /><span>{{ t('launchEditor.enabled') }}</span></label>
        <button type="button" class="icon-button danger" :aria-label="t('launchEditor.deleteModel')" @click="config.models.splice(index, 1)"><IconTrash :size="16" /></button>
      </div>
    </template>

    <div class="profile-lower-grid launch-editor-grid">
      <div class="page-stack compact-stack">
        <label class="search-box full"><IconSearch :size="17" /><input v-model="search" :placeholder="t('launchEditor.searchArgs')" /></label>
        <div class="argument-catalog launch-catalog">
          <div v-if="!filteredCatalog.length" class="empty-state compact catalog-empty">
            {{ catalog.length ? t('launchEditor.noMatches') : t('launchEditor.emptyCatalog') }}
          </div>
          <button v-for="item in filteredCatalog" :key="item.id" type="button" class="catalog-row" @click="addArgument(item)">
            <span><code>{{ item.aliases.join(' / ') || item.key }}</code><small>{{ item.description || item.value_hint }}</small></span>
            <em>{{ item.category }}</em>
          </button>
        </div>
      </div>

      <div class="page-stack compact-stack">
        <div v-if="!config.catalog_args.length" class="empty-state compact">{{ t('launchEditor.noSelectedArgs') }}</div>
        <div v-for="(item, index) in config.catalog_args" :key="`${item.flag}-${index}`" class="arg-edit-row">
          <input v-model.trim="item.flag" class="flag-input" />
          <input v-model="item.value" :placeholder="t('launchEditor.optionalValue')" />
          <button type="button" class="icon-button" :aria-label="t('launchEditor.removeArg')" @click="config.catalog_args.splice(index, 1)"><IconX :size="17" /></button>
        </div>
        <label class="field">
          <span>{{ t('launchEditor.customArgs') }}</span>
          <textarea v-model="config.custom_args_text" rows="7" spellcheck="false" placeholder="-np 1&#10;--cache-type-k q8_0" />
          <small>{{ t('launchEditor.customArgsHint') }}</small>
        </label>
      </div>
    </div>
  </div>
</template>
