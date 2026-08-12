<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { IconKey, IconArrowRight } from '@tabler/icons-vue'
import { api, jsonBody, setAuthToken } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const route = useRoute()
const store = useAppStore()
const token = ref('')
const submitting = ref(false)

async function submit() {
  const value = token.value.trim()
  if (!value) return
  submitting.value = true
  try {
    await api('/auth/login', { method: 'POST', ...jsonBody({ token: value }) })
    setAuthToken(value)
    const redirect = (route.query.redirect as string) || '/'
    await router.replace(redirect)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '登录失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-mark">LL</div>
      <h2>LlamaLens</h2>
      <p class="login-hint">请输入访问令牌以继续</p>
      <label class="field">
        <span>API 令牌</span>
        <div class="input-row">
          <IconKey :size="18" :stroke-width="1.8" />
          <input
            v-model="token"
            type="password"
            autocomplete="current-password"
            placeholder="Bearer token"
            required
            :disabled="submitting"
            autofocus
          />
        </div>
      </label>
      <button class="button primary" type="submit" :disabled="submitting || !token.trim()">
        <IconArrowRight :size="17" />登录
      </button>
    </form>
  </div>
</template>
