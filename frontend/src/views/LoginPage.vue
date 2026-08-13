<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { IconKey, IconArrowRight } from '@tabler/icons-vue'
import { authApi, setAuthToken } from '../api'
import { useAppStore } from '../stores/app'

const { t } = useI18n()
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
    await authApi.login(value)
    setAuthToken(value)
    const redirect = (route.query.redirect as string) || '/'
    await router.replace(redirect)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('auth.loginFailed'))
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
      <p class="login-hint">{{ t('auth.tokenRequired') }}</p>
      <label class="field">
        <span>{{ t('auth.tokenLabel') }}</span>
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
        <IconArrowRight :size="17" />{{ t('auth.login') }}
      </button>
    </form>
  </div>
</template>
