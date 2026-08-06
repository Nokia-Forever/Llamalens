import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: (localStorage.getItem('llamalens-theme') || 'system') as 'light' | 'dark' | 'system',
    notices: [] as Array<{ id: number; type: 'success' | 'error' | 'info'; message: string }>,
  }),
  actions: {
    applyTheme() {
      const dark = this.theme === 'dark' || (this.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
      document.documentElement.dataset.theme = dark ? 'dark' : 'light'
      localStorage.setItem('llamalens-theme', this.theme)
    },
    cycleTheme() {
      this.theme = this.theme === 'system' ? 'light' : this.theme === 'light' ? 'dark' : 'system'
      this.applyTheme()
    },
    notify(type: 'success' | 'error' | 'info', message: string) {
      const id = Date.now() + Math.random()
      this.notices.push({ id, type, message })
      window.setTimeout(() => (this.notices = this.notices.filter((item) => item.id !== id)), 4200)
    },
  },
})
