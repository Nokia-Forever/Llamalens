<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  IconActivity,
  IconAdjustments,
  IconBox,
  IconChartHistogram,
  IconChartLine,
  IconGauge,
  IconListCheck,
  IconMoon,
  IconServer,
  IconSettings,
} from '@tabler/icons-vue'
import { useAppStore } from './stores/app'

const { t } = useI18n()
const route = useRoute()
const store = useAppStore()
const title = computed(() => String(route.meta.title || 'LlamaLens'))
const isLoginPage = computed(() => route.path === '/login')
const nav = computed(() => [
  { to: '/', label: t('nav.dashboard'), icon: IconGauge },
  { to: '/services', label: t('nav.services'), icon: IconServer },
  { to: '/models', label: t('nav.models'), icon: IconBox },
  { to: '/profiles', label: t('nav.profiles'), icon: IconAdjustments },
  { to: '/benchmark', label: t('nav.benchmarks'), icon: IconActivity },
  { to: '/tasks', label: t('nav.tasks'), icon: IconListCheck },
  { to: '/results', label: t('nav.results'), icon: IconChartHistogram },
  { to: '/observation', label: t('nav.observation'), icon: IconChartLine },
  { to: '/settings', label: t('nav.settings'), icon: IconSettings },
])

onMounted(() => store.applyTheme())
</script>

<template>
  <div v-if="isLoginPage" class="login-shell">
    <RouterView />
    <div class="notice-stack" aria-live="polite">
      <div v-for="notice in store.notices" :key="notice.id" class="notice" :class="`notice-${notice.type}`">{{ notice.message }}</div>
    </div>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">LL</div>
        <div><strong>LlamaLens</strong><span>{{ t('common.console') }}</span></div>
      </div>
      <nav class="main-nav" :aria-label="t('common.mainNav')">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to">
          <component :is="item.icon" :size="19" :stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <button class="theme-button" type="button" @click="store.cycleTheme">
        <IconMoon :size="18" :stroke-width="1.8" />{{ t('common.theme') }}: {{ store.theme }}
      </button>
    </aside>

    <main class="main-area">
      <header class="topbar"><h1>{{ title }}</h1><div class="topbar-note">{{ t('common.localConsole') }}</div></header>
      <div class="page-container"><RouterView /></div>
    </main>

    <div class="notice-stack" aria-live="polite">
      <div v-for="notice in store.notices" :key="notice.id" class="notice" :class="`notice-${notice.type}`">{{ notice.message }}</div>
    </div>
  </div>
</template>
