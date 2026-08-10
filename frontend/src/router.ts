import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/DashboardPage.vue'), meta: { title: '概览' } },
    { path: '/services', component: () => import('./views/ServicesPage.vue'), meta: { title: 'Llama Services' } },
    { path: '/models', component: () => import('./views/ModelsPage.vue'), meta: { title: '模型库' } },
    { path: '/profiles', component: () => import('./views/ProfilesPage.vue'), meta: { title: 'Profiles' } },
    { path: '/benchmark', component: () => import('./views/BenchmarkPage.vue'), meta: { title: '新建/编辑任务' } },
    { path: '/tasks', component: () => import('./views/TasksPage.vue'), meta: { title: '任务' } },
    { path: '/results', component: () => import('./views/ResultsPage.vue'), meta: { title: '结果' } },
    { path: '/observation', component: () => import('./views/ObservationPage.vue'), meta: { title: '观测' } },
    { path: '/settings', component: () => import('./views/SettingsPage.vue'), meta: { title: '设置' } },
  ],
})
