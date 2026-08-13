import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { authApi } from './api'
import { useAppStore } from './stores/app'
import { i18n } from './i18n'
import './styles.css'

async function bootstrap() {
  const pinia = createPinia()
  const app = createApp(App)
  app.use(pinia)
  app.use(i18n)
  const store = useAppStore()
  try {
    const status = await authApi.status()
    store.setAuthRequired(status.auth_required)
  } catch {
    store.setAuthRequired(false)
  }
  app.use(router)
  app.mount('#app')
}

void bootstrap()
