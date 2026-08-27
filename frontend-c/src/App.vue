<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { BadgeCheck, Bell, Bot, CalendarDays, Compass, LogIn, LogOut, Menu, MessageCircle, Newspaper, Search, Settings, ShoppingBag, Users, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { getUnreadSummary } from '@/features/notifications/api'
import { getPrivateImageUrl } from '@/features/media/api'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const totalUnread = ref(0)
const accountAvatarUrl = ref('')
let pollTimer: ReturnType<typeof setInterval> | undefined
const links = computed(() => [
  { to: '/', label: '发现', icon: Compass, public: true },
  { to: '/itineraries', label: '我的计划', icon: CalendarDays, public: false },
  { to: '/assistant', label: '智能助手', icon: Bot, public: false },
  { to: '/community', label: '田野笔记', icon: Newspaper, public: true },
  { to: '/companions', label: '同行计划', icon: Users, public: true },
  { to: '/memberships', label: '会员中心', icon: BadgeCheck, public: true },
  { to: '/me/access', label: '我的权益', icon: BadgeCheck, public: false },
  { to: '/messages', label: '群聊消息', icon: MessageCircle, public: false },
  { to: '/notifications', label: '群聊未读', icon: Bell, public: false },
  { to: '/travel/search', label: '出行搜索', icon: Search, public: false },
  { to: '/me/orders', label: '我的订单', icon: ShoppingBag, public: false },
  { to: '/me/settings', label: '个人设置', icon: Settings, public: false },
].filter((link) => link.public || auth.isConsumerSession))
const desktopLinks = computed(() => links.value.filter((link) => !['/messages', '/notifications', '/me/settings'].includes(link.to)).slice(0, 7))

async function refreshUnreadCounts() {
  if (!auth.isConsumerSession) {
    totalUnread.value = 0
    return
  }
  try {
    const summary = await getUnreadSummary()
    totalUnread.value = summary.total_unread
  } catch {
    // Navigation remains usable when badge polling is temporarily unavailable.
  }
}

function badge(value: number) { return value > 99 ? '99+' : String(value) }

async function refreshAccountAvatar() {
  accountAvatarUrl.value = ''
  const assetId = auth.user?.avatar_asset_id
  if (!assetId) return
  try { accountAvatarUrl.value = await getPrivateImageUrl(assetId) } catch { /* Use the nickname initial when the private asset is unavailable. */ }
}

async function logout() { await auth.logout(); menuOpen.value = false; if (route.meta.requiresConsumer) await router.replace('/login') }
function closeMenu() { menuOpen.value = false }
onMounted(() => {
  void refreshUnreadCounts()
  void refreshAccountAvatar()
  pollTimer = setInterval(refreshUnreadCounts, 20000)
  window.addEventListener('focus', refreshUnreadCounts)
  window.addEventListener('unread-counts:refresh', refreshUnreadCounts)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  window.removeEventListener('focus', refreshUnreadCounts)
  window.removeEventListener('unread-counts:refresh', refreshUnreadCounts)
})
watch(() => auth.isConsumerSession, refreshUnreadCounts)
watch(() => auth.user?.avatar_asset_id, () => void refreshAccountAvatar())
</script>

<template>
  <el-container class="shell">
    <el-header class="topbar">
      <RouterLink class="brand" to="/" @click="closeMenu"><span class="brand-mark">行迹</span><span class="brand-caption">TRAVEL, AT YOUR PACE</span></RouterLink>
      <nav class="desktop-nav" aria-label="Primary navigation"><RouterLink v-for="link in desktopLinks" :key="link.to" :to="link.to" :class="{ active: route.path === link.to || (link.to !== '/' && route.path.startsWith(`${link.to}/`)) }"><component :is="link.icon" :size="16" />{{ link.label }}</RouterLink></nav>
        <div class="account"><template v-if="auth.isConsumerSession"><RouterLink class="account-action" to="/messages" title="消息" aria-label="消息"><MessageCircle :size="18" /></RouterLink><RouterLink class="account-action" to="/notifications" title="群聊未读消息" aria-label="群聊未读消息"><Bell :size="18" /><span v-if="totalUnread" class="badge">{{ badge(totalUnread) }}</span></RouterLink><RouterLink class="personal-center" to="/me/settings" title="个人中心与设置"><span class="account-avatar" aria-hidden="true"><img v-if="accountAvatarUrl" :src="accountAvatarUrl" alt="" /><template v-else>{{ (auth.user?.nickname || '我').charAt(0).toUpperCase() }}</template></span><span class="account-name">{{ auth.user?.nickname || '我的' }}</span></RouterLink><button type="button" title="退出登录" @click="logout"><LogOut :size="17" /></button></template><RouterLink v-else class="sign-in" to="/login"><LogIn :size="16" />登录</RouterLink><button class="menu-toggle" type="button" :aria-expanded="menuOpen" aria-label="打开导航" @click="menuOpen = !menuOpen"><X v-if="menuOpen" :size="20" /><Menu v-else :size="20" /></button></div>
    </el-header>
    <Transition name="nav-drop">
      <nav v-if="menuOpen" class="mobile-nav" aria-label="Mobile navigation"><RouterLink v-for="link in links" :key="link.to" :to="link.to" :class="{ active: route.path === link.to || (link.to !== '/' && route.path.startsWith(`${link.to}/`)) }" @click="closeMenu"><component :is="link.icon" :size="17" /><span>{{ link.to === '/me/settings' ? '个人中心与设置' : link.to === '/notifications' ? '群聊未读消息' : link.label }}</span><span v-if="link.to === '/notifications' && totalUnread" class="mobile-badge">{{ badge(totalUnread) }}</span></RouterLink></nav>
    </Transition>
    <el-main class="content"><RouterView /></el-main>
  </el-container>
</template>

<style scoped>
.shell { background: var(--field-paper); min-height: 100dvh; }

.topbar {
  align-items: center;
  background: rgba(245, 248, 246, .88);
  border-bottom: 1px solid rgba(19, 43, 58, .08);
  color: var(--field-ink);
  display: flex;
  gap: 30px;
  height: 72px;
  padding: 0 clamp(20px, 4vw, 60px);
  position: sticky;
  top: 0;
  z-index: 20;
  backdrop-filter: blur(16px) saturate(1.4);
  animation: topbar-drop var(--motion-slow) var(--ease-out) both;
}
@keyframes topbar-drop { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: translateY(0); } }

.brand {
  align-items: baseline;
  color: var(--field-ink);
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  text-decoration: none;
  white-space: nowrap;
  transition: opacity var(--motion-fast) var(--ease-standard);
}
.brand:hover { opacity: 0.7; }
.brand-mark { font-size: 24px; font-weight: 900; letter-spacing: .08em; line-height: 1; }
.brand-caption { color: var(--field-muted); font: 700 9px/1 var(--field-mono); letter-spacing: .12em; }

.desktop-nav { align-items: center; display: flex; flex: 1; gap: 4px; }
.desktop-nav a, .sign-in {
  align-items: center;
  border-radius: 8px;
  color: var(--field-ink-soft);
  display: inline-flex;
  font-size: 13px;
  font-weight: 700;
  gap: 7px;
  padding: 9px 10px;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}
.desktop-nav a:hover, .sign-in:hover { background: var(--travel-sky); color: var(--field-teal); transform: translateY(-1px); }
.desktop-nav a:active, .sign-in:active { transform: translateY(0) scale(0.98); }
.desktop-nav a.active { background: var(--field-teal-soft); color: var(--field-teal); }

.account { align-items: center; display: flex; gap: 5px; margin-left: auto; }
.account-action, .personal-center {
  align-items: center;
  border-radius: 8px;
  color: var(--field-ink-soft);
  display: inline-flex;
  gap: 7px;
  padding: 8px;
  position: relative;
  text-decoration: none;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}
.personal-center { font-size: 13px; font-weight: 800; padding: 6px 10px 6px 6px; }

.account-avatar {
  align-items: center;
  background: var(--field-teal);
  border-radius: 999px;
  color: #fff;
  display: inline-flex;
  font: 800 12px/1 var(--field-mono);
  height: 24px;
  justify-content: center;
  width: 24px;
  overflow: hidden;
}
.account-avatar img { height: 100%; object-fit: cover; width: 100%; }
.account-action:hover, .personal-center:hover { background: var(--travel-sky); color: var(--field-teal); transform: translateY(-1px); }
.account-action:active, .personal-center:active { transform: scale(0.97); }

.badge {
  align-items: center;
  background: #c9362b;
  border: 2px solid var(--field-paper);
  border-radius: 999px;
  color: #fff;
  display: flex;
  font: 800 9px/1 var(--field-mono);
  height: 18px;
  justify-content: center;
  min-width: 18px;
  padding: 0 3px;
  position: absolute;
  right: -3px;
  top: -4px;
  animation: badge-pop var(--motion-base) var(--ease-out) both;
}
@keyframes badge-pop { 0% { transform: scale(0); } 60% { transform: scale(1.15); } 100% { transform: scale(1); } }

.account button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 8px;
  color: var(--field-ink-soft);
  cursor: pointer;
  display: inline-flex;
  padding: 8px;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}
.account button:hover { background: var(--travel-sky); color: var(--field-teal); transform: translateY(-1px); }
.account button:active { transform: scale(0.96); }

.sign-in { background: var(--field-deep); color: #fff !important; padding: 9px 16px; }
.sign-in:hover { background: var(--field-teal); transform: translateY(-1px); }

.menu-toggle {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-line);
  border-radius: 8px;
  color: var(--field-ink);
  cursor: pointer;
  display: none;
  padding: 8px;
  transition: background-color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}
.menu-toggle:hover { background: var(--travel-sky); border-color: var(--field-teal); }
.menu-toggle:active { transform: scale(0.95); }
.menu-toggle svg { transition: transform var(--motion-base) var(--ease-out); }

.mobile-nav {
  background: var(--field-white);
  border-bottom: 1px solid var(--field-line);
  box-shadow: 0 12px 28px rgba(19, 43, 58, .08);
  display: grid;
  gap: 2px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding: 12px clamp(16px, 4vw, 40px) 18px;
  position: sticky;
  top: 72px;
  z-index: 19;
}
.mobile-nav a {
  align-items: center;
  border-radius: 10px;
  color: var(--field-ink-soft);
  display: inline-flex;
  font-size: 14px;
  font-weight: 700;
  gap: 10px;
  padding: 12px 12px;
  position: relative;
  text-decoration: none;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}
.mobile-nav a:hover { background: var(--travel-sky); color: var(--field-teal); transform: translateX(2px); }
.mobile-nav a:active { transform: scale(0.98); }
.mobile-nav a.active { background: var(--field-teal-soft); color: var(--field-teal); }
.mobile-badge {
  align-items: center;
  background: #c9362b;
  border-radius: 999px;
  color: #fff;
  display: inline-flex;
  font: 800 10px/1 var(--field-mono);
  justify-content: center;
  margin-left: auto;
  min-width: 20px;
  padding: 3px 6px;
}

.content { padding: 0; }

.nav-drop-enter-active { transition: opacity var(--motion-base) var(--ease-out), transform var(--motion-base) var(--ease-out); overflow: hidden; }
.nav-drop-leave-active { transition: opacity var(--motion-fast) var(--ease-out), transform var(--motion-fast) var(--ease-out); overflow: hidden; }
.nav-drop-enter-from, .nav-drop-leave-to { opacity: 0; transform: translateY(-8px); }

@media (max-width: 1100px) {
  .desktop-nav { display: none; }
  .menu-toggle { display: inline-flex; }
  .mobile-nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .personal-center .account-name { display: none; }
}
@media (max-width: 520px) {
  .topbar { height: 64px; padding: 0 16px; }
  .brand-mark { font-size: 21px; }
  .mobile-nav { top: 64px; grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .topbar, .badge { animation: none; }
  .desktop-nav a, .sign-in, .account-action, .personal-center, .account button, .mobile-nav a, .brand { transition: none; transform: none; }
}
</style>
