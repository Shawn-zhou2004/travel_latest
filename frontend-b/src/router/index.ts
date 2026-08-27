import { createMemoryHistory, createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/features/auth/LoginPage.vue'), meta: { guestOnly: true } },
  { path: '/', redirect: () => useAuthStore().isProviderSession && !useAuthStore().isAdminSession ? '/provider/experiences' : '/content/posts' },
  { path: '/provider/experiences', component: () => import('@/features/provider/pages/ProviderExperiencesPage.vue'), meta: { requiresProvider: true } },
  { path: '/provider/bookings', component: () => import('@/features/provider/pages/ProviderBookingsPage.vue'), meta: { requiresProvider: true } },
  { path: '/users', component: () => import('@/features/admin/pages/UsersPage.vue'), meta: { requiresAdmin: true } },
  { path: '/content/posts', component: () => import('@/features/admin/pages/OperationsPage.vue'), props: { area: 'content' }, meta: { requiresAdmin: true } },
  { path: '/content/companions', component: () => import('@/features/admin/pages/OperationsPage.vue'), props: { area: 'companions' }, meta: { requiresAdmin: true } },
  { path: '/content/reports', component: () => import('@/features/admin/pages/OperationsPage.vue'), props: { area: 'reports' }, meta: { requiresAdmin: true } },
  { path: '/providers', component: () => import('@/features/admin/pages/OperationsPage.vue'), props: { area: 'providers' }, meta: { requiresAdmin: true } },
  { path: '/orders', component: () => import('@/features/admin/pages/OperationsPage.vue'), props: { area: 'orders' }, meta: { requiresAdmin: true } },
  { path: '/ai', component: () => import('@/features/admin/pages/AiOperationsPage.vue'), meta: { requiresAdmin: true } },
  { path: '/ai/poi-candidates', component: () => import('@/features/admin/pages/PoiCandidatesPage.vue'), meta: { requiresAdmin: true } },
  { path: '/tasks', component: () => import('@/features/exports/pages/ExportTasksPage.vue'), meta: { requiresAdmin: true } },
  { path: '/memberships/plans', component: () => import('@/features/membership/pages/MembershipPlansPage.vue'), meta: { requiresAdmin: true } },
  { path: '/memberships/purchases', component: () => import('@/features/membership/pages/MembershipPurchasesPage.vue'), meta: { requiresAdmin: true } },
  { path: '/search', component: () => import('@/features/admin/pages/SearchIndexesPage.vue'), meta: { requiresAdmin: true } },
  { path: '/no-access', component: () => import('@/features/auth/NoAccessPage.vue') },
]

function defaultHistory(): RouterHistory {
  return typeof window === 'undefined' ? createMemoryHistory() : createWebHistory()
}

export function createAdminRouter(history: RouterHistory = defaultHistory()) {
  const router = createRouter({ history, routes })
  router.beforeEach((to) => {
    const auth = useAuthStore()
    if (!auth.initialized) {
      return auth.restoreSession().then(() => {
        if (to.meta.guestOnly && (auth.isAdminSession || auth.isProviderSession)) return auth.isProviderSession ? '/provider/experiences' : '/'
        if (to.meta.requiresProvider && auth.isProviderSession && !auth.isAdminSession) return true
        if (to.meta.requiresProvider) return { path: '/login', query: { redirect: to.fullPath } }
        if (!to.meta.requiresAdmin || auth.isAdminSession) return true
        return { path: '/login', query: { redirect: to.fullPath } }
      })
    }
    if (to.meta.guestOnly && (auth.isAdminSession || auth.isProviderSession)) return auth.isProviderSession ? '/provider/experiences' : '/'
    if (to.meta.requiresProvider && auth.isProviderSession && !auth.isAdminSession) return true
    if (to.meta.requiresProvider) return { path: '/login', query: { redirect: to.fullPath } }
    if (!to.meta.requiresAdmin || auth.isAdminSession) return true
    return { path: '/login', query: { redirect: to.fullPath } }
  })
  return router
}

export default createAdminRouter()
