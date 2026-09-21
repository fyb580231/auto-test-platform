/**
 * 路由配置与全局前置守卫。
 *
 * - `/login` 为独立无布局页面（`meta.public = true`）；
 * - 其余路由统一渲染在 `App.vue` 的侧边栏主框架内；
 * - 守卫负责：未登录跳登录页、已登录访问登录页跳首页、设置 `document.title`。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useUserStore } from '@/stores/user'

/** 站点标题（来自环境变量，便于多环境区分） */
const APP_TITLE = import.meta.env.VITE_APP_TITLE || '一体化自动化测试平台'

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题：用于面包屑与 document.title */
    title: string
    /** 是否为免登录页面 */
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '首页' },
  },
  {
    path: '/projects',
    name: 'projects',
    component: () => import('@/views/ProjectList.vue'),
    meta: { title: '项目管理' },
  },
  {
    path: '/cases',
    name: 'cases',
    component: () => import('@/views/TestCaseList.vue'),
    meta: { title: '用例管理' },
  },
  {
    path: '/suites',
    name: 'suites',
    component: () => import('@/views/TestSuiteList.vue'),
    meta: { title: '用例集' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/views/TaskList.vue'),
    meta: { title: '执行历史' },
  },
  {
    path: '/environments',
    name: 'environments',
    component: () => import('@/views/EnvironmentConfig.vue'),
    meta: { title: '环境配置' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const userStore = useUserStore()
  document.title = `${to.meta.title} · ${APP_TITLE}`

  if (to.meta.public) {
    // 已登录用户访问登录页时直接进入首页
    return to.path === '/login' && userStore.isLoggedIn ? { path: '/' } : true
  }

  if (!userStore.isLoggedIn) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }

  // 已登录但缺少用户信息（刷新页面 / 新标签页）时补拉一次，失败由拦截器统一处理
  if (!userStore.userInfo) {
    void userStore.fetchMe().catch(() => undefined)
  }
  return true
})

export default router
