import { createMemoryHistory, createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/', component: () => import('@/features/home/HomePage.vue') },
  { path: '/login', component: () => import('@/features/auth/LoginPage.vue'), meta: { guestOnly: true } },
  { path: '/register', component: () => import('@/features/auth/RegisterPage.vue'), meta: { guestOnly: true } },
  { path: '/plan', component: () => import('@/features/itineraries/pages/PlanPage.vue'), meta: { requiresConsumer: true } },
  { path: '/assistant', component: () => import('@/features/ai/pages/AiAssistantPage.vue'), meta: { requiresConsumer: true } },
  { path: '/itineraries', component: () => import('@/features/itineraries/pages/ItinerariesPage.vue'), meta: { requiresConsumer: true } },
  { path: '/itineraries/:itineraryId', component: () => import('@/features/itineraries/pages/ItineraryWorkspacePage.vue'), props: true, meta: { requiresConsumer: true } },
  { path: '/shared/itineraries/:itineraryId', component: () => import('@/features/itineraries/pages/SharedItineraryPage.vue'), props: true },
  { path: '/community', component: () => import('@/features/community/FieldNotesPage.vue') },
  { path: '/community/mine', component: () => import('@/features/community/FieldNotesMinePage.vue'), meta: { requiresConsumer: true } },
  { path: '/community/:postId', component: () => import('@/features/community/FieldNoteDetailPage.vue'), props: true },
   { path: '/itineraries/:itineraryId/publish-field-note', component: () => import('@/features/community/FieldNotePublishPage.vue'), props: true, meta: { requiresConsumer: true } },
   { path: '/itineraries/:itineraryId/publish-companion-plan', component: () => import('@/features/community/CompanionPlanPublishPage.vue'), props: true, meta: { requiresConsumer: true } },
   { path: '/companions', component: () => import('@/features/community/CompanionPlansPage.vue') },
   { path: '/companions/publish-activity', component: () => import('@/features/community/CompanionActivityPublishPage.vue'), meta: { requiresConsumer: true } },
  { path: '/companions/:requestId', component: () => import('@/features/community/CompanionPlanDetailPage.vue'), props: true },
  { path: '/memberships', component: () => import('@/features/membership/MembershipPlansPage.vue') },
  { path: '/memberships/pay/:purchaseId', component: () => import('@/features/membership/MembershipQrPaymentPage.vue'), props: true, meta: { requiresConsumer: true } },
  { path: '/memberships/return/:purchaseId', component: () => import('@/features/membership/MembershipPurchaseReturnPage.vue'), props: true, meta: { requiresConsumer: true } },
  { path: '/experiences', component: () => import('@/features/experiences/ExperiencesPage.vue') },
  { path: '/experiences/:experienceId', component: () => import('@/features/experiences/ExperienceDetailPage.vue'), props: true },
  { path: '/me/access', component: () => import('@/features/membership/MyEntitlementsPage.vue'), meta: { requiresConsumer: true } },
  { path: '/travel/search', component: () => import('@/features/orders/pages/SearchPage.vue'), meta: { requiresConsumer: true } },
  { path: '/me/settings', component: () => import('@/features/settings/SettingsPage.vue'), meta: { requiresConsumer: true } },
  { path: '/me/profile', redirect: { path: '/me/settings', hash: '#profile' }, meta: { requiresConsumer: true } },
  { path: '/me/orders', component: () => import('@/features/orders/pages/OrdersPage.vue'), meta: { requiresConsumer: true } },
  { path: '/notifications', component: () => import('@/features/notifications/NotificationsPage.vue'), meta: { requiresConsumer: true } },
  { path: '/payments/alipay/return', component: () => import('@/features/orders/pages/AlipayReturnPage.vue'), meta: { requiresConsumer: true } },
  {
    path: '/messages/:conversationId?',
    component: () => import('@/features/chat/ChatPage.vue'),
    props: (route) => ({ conversationId: typeof route.params.conversationId === 'string' ? route.params.conversationId : undefined }),
    meta: { requiresConsumer: true },
  },
  { path: '/no-access', component: () => import('@/features/auth/NoAccessPage.vue') },
]

export { routes }

function defaultHistory(): RouterHistory {
  return typeof window === 'undefined' ? createMemoryHistory() : createWebHistory()
}

export function createConsumerRouter(history: RouterHistory = defaultHistory()) {
  const router = createRouter({ history, routes })
  router.beforeEach((to) => {
    const auth = useAuthStore()
    if (!auth.initialized) {
      return auth.restoreSession().then(() => {
        if (to.meta.guestOnly && auth.isConsumerSession) return '/'
        if (!to.meta.requiresConsumer || auth.isConsumerSession) return true
        return { path: '/login', query: { redirect: to.fullPath } }
      })
    }
    if (to.meta.guestOnly && auth.isConsumerSession) return '/'
    if (!to.meta.requiresConsumer || auth.isConsumerSession) return true
    return { path: '/login', query: { redirect: to.fullPath } }
  })
  return router
}

export default createConsumerRouter()
