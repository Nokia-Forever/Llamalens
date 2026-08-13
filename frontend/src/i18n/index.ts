import { createI18n } from 'vue-i18n'
import zh from './locales/zh.json'
import en from './locales/en.json'

const saved = localStorage.getItem('locale')
export type Locale = 'zh' | 'en'

export const i18n = createI18n({
  legacy: false,
  locale: saved === 'en' ? 'en' : 'zh',
  fallbackLocale: 'zh',
  messages: { zh, en },
})

export function setLocale(lang: Locale) {
  i18n.global.locale.value = lang
  localStorage.setItem('locale', lang)
}

export function getLocale(): Locale {
  return i18n.global.locale.value === 'en' ? 'en' : 'zh'
}
