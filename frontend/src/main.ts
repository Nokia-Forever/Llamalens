import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { api } from './api'
import { useAppStore } from './stores/app'
import './styles.css'

async function bootstrap() {
  const pinia = createPinia()
  const app = createApp(App)
  app.use(pinia)
  const store = useAppStore()
  try {
    const status = await api<{ auth_required: boolean }>('/auth/status')
    store.setAuthRequired(status.auth_required)
  } catch {
    store.setAuthRequired(false)
  }
  app.use(router)
  app.mount('#app')
}

void bootstrap()
