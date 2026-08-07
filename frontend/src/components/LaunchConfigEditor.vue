<script setup lang="ts">
import { computed, ref } from 'vue'
import { IconPlus, IconSearch, IconTrash, IconX } from '@tabler/icons-vue'
import type { CatalogArgument, LaunchConfig, ModelFile } from '../types'

const props = defineProps<{ config: LaunchConfig; models: ModelFile[]; catalog: CatalogArgument[] }>()
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
        <span>启动模式</span>
        <select v-model="config.mode">
          <option value="single">单模型</option>
          <option value="router">Router 多模型</option>
        </select>
      </label>
      <label v-if="config.mode === 'single'" class="field">
        <span>模型 Alias</span>
        <input v-model.trim="config.model_alias" required placeholder="例如 qwen-32b" />
      </label>
    </div>

    <div v-if="config.mode === 'single'" class="form-grid two-columns">
      <label class="field">
        <span>GGUF 模型路径</span>
        <input v-model.trim="config.model_path" :list="modelListId" required placeholder="/srv/models/model.gguf" />
        <small>可从已扫描模型中选择，也可以直接输入路径。</small>
      </label>
    </div>

    <template v-else>
      <div class="form-grid two-columns">
        <label class="field"><span>--models-dir</span><input v-model.trim="config.models_dir" required placeholder="/srv/models" /></label>
        <label class="field"><span>--models-preset</span><input v-model.trim="config.models_preset" placeholder="可选 preset 文件或名称" /></label>
        <label class="field"><span>--models-max</span><input v-model.number="config.models_max" type="number" min="0" /></label>
        <label class="check-field"><input v-model="config.models_autoload" type="checkbox" /><span>启用 --models-autoload</span></label>
      </div>

      <div class="pane-heading">
        <div><strong>Router 模型 Alias</strong><small>这些 alias 会在部署后提供给 Benchmark 选择。</small></div>
        <button type="button" class="button secondary" @click="addRouterModel"><IconPlus :size="16" />添加模型</button>
      </div>
      <div v-if="!config.models.length" class="empty-state compact">至少添加一个启用的模型 alias。</div>
      <div v-for="(model, index) in config.models" :key="index" class="form-grid router-model-row">
        <input v-model.trim="model.alias" placeholder="必填 alias" required />
        <input v-model="model.display_name" placeholder="显示名称，可选" />
        <input v-model.trim="model.model_path" :list="modelListId" placeholder="模型路径，可由目录/preset 发现" />
        <label class="check-field compact-check"><input v-model="model.enabled" type="checkbox" /><span>启用</span></label>
        <button type="button" class="icon-button danger" aria-label="删除模型" @click="config.models.splice(index, 1)"><IconTrash :size="16" /></button>
      </div>
    </template>

    <div class="profile-lower-grid launch-editor-grid">
      <div class="page-stack compact-stack">
        <label class="search-box full"><IconSearch :size="17" /><input v-model="search" placeholder="搜索 parallel、batch、GPU 或 flag" /></label>
        <div class="argument-catalog launch-catalog">
          <div v-if="!filteredCatalog.length" class="empty-state compact catalog-empty">
            {{ catalog.length ? '没有匹配的参数。' : '参数目录为空，可先在 Profile 页面刷新本机参数。' }}
          </div>
          <button v-for="item in filteredCatalog" :key="item.id" type="button" class="catalog-row" @click="addArgument(item)">
            <span><code>{{ item.aliases.join(' / ') || item.key }}</code><small>{{ item.description || item.value_hint }}</small></span>
            <em>{{ item.category }}</em>
          </button>
        </div>
      </div>

      <div class="page-stack compact-stack">
        <div v-if="!config.catalog_args.length" class="empty-state compact">尚未选择目录参数。</div>
        <div v-for="(item, index) in config.catalog_args" :key="`${item.flag}-${index}`" class="arg-edit-row">
          <input v-model.trim="item.flag" class="flag-input" />
          <input v-model="item.value" placeholder="值，可留空" />
          <button type="button" class="icon-button" aria-label="移除参数" @click="config.catalog_args.splice(index, 1)"><IconX :size="17" /></button>
        </div>
        <label class="field">
          <span>自定义 llama 参数</span>
          <textarea v-model="config.custom_args_text" rows="7" spellcheck="false" placeholder="-np 1&#10;--cache-type-k q8_0" />
          <small>每行一个参数片段，按顺序追加到目录参数之后。</small>
        </label>
      </div>
    </div>
  </div>
</template>
