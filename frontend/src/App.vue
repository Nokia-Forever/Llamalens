<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  IconActivity,
  IconAdjustments,
  IconBox,
  IconChartHistogram,
  IconGauge,
  IconMoon,
  IconServer,
  IconSettings,
} from '@tabler/icons-vue'
import { useAppStore } from './stores/app'

const route = useRoute()
const store = useAppStore()
const title = computed(() => String(route.meta.title || 'LlamaLens'))
const nav = [
  { to: '/', label: '概览', icon: IconGauge },
  { to: '/services', label: 'Services', icon: IconServer },
  { to: '/models', label: '模型库', icon: IconBox },
  { to: '/profiles', label: 'Profiles', icon: IconAdjustments },
  { to: '/benchmark', label: 'Benchmark', icon: IconActivity },
  { to: '/results', label: '结果', icon: IconChartHistogram },
  { to: '/settings', label: '设置', icon: IconSettings },
]

onMounted(() => store.applyTheme())
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">LL</div>
        <div><strong>LlamaLens</strong><span>llama.cpp console</span></div>
      </div>
      <nav class="main-nav" aria-label="主导航">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to">
          <component :is="item.icon" :size="19" :stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <button class="theme-button" type="button" @click="store.cycleTheme">
        <IconMoon :size="18" :stroke-width="1.8" />主题: {{ store.theme }}
      </button>
    </aside>

    <main class="main-area">
      <header class="topbar"><h1>{{ title }}</h1><div class="topbar-note">本机控制台</div></header>
      <div class="page-container"><RouterView /></div>
    </main>

    <div class="notice-stack" aria-live="polite">
      <div v-for="notice in store.notices" :key="notice.id" class="notice" :class="`notice-${notice.type}`">{{ notice.message }}</div>
    </div>
  </div>
</template>
