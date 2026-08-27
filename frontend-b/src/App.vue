<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { BadgeCheck, Bot, CalendarDays, ClipboardList, FileWarning, LayoutDashboard, LogIn, LogOut, MapPinned, ReceiptText, Search, ShoppingBag, Store, Users } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const links = computed(() => [
  { to: '/content/posts', label: '审核工作台', icon: LayoutDashboard },
  { to: '/users', label: '用户', icon: Users },
  { to: '/content/companions', label: '结伴审核', icon: ClipboardList },
  { to: '/content/reports', label: '举报处理', icon: FileWarning },
  { to: '/providers', label: '供应商审核', icon: Store },
  { to: '/orders', label: '订单查询', icon: ShoppingBag },
   { to: '/ai', label: 'AI 运营', icon: Bot },
   { to: '/ai/poi-candidates', label: '景点候选审核', icon: MapPinned },
  { to: '/tasks', label: '任务', icon: ClipboardList },
  { to: '/memberships/plans', label: '会员计划', icon: BadgeCheck },
  { to: '/memberships/purchases', label: '会员购买', icon: ReceiptText },
  { to: '/search', label: '搜索', icon: Search },
])
const providerLinks = [{ to: '/provider/experiences', label: '体验服务', icon: CalendarDays }, { to: '/provider/bookings', label: '预订核销', icon: ClipboardList }]
const isProviderWorkspace = computed(() => auth.isProviderSession && !auth.isAdminSession)
async function logout() { await auth.logout(); if (route.meta.requiresAdmin || route.meta.requiresProvider) await router.replace('/login') }
</script>

<template>
  <el-container class="shell">
    <el-header class="topbar"><RouterLink class="brand" :to="isProviderWorkspace ? '/provider/experiences' : '/'">{{ isProviderWorkspace ? 'Provider Workspace' : 'Platform Administration' }}</RouterLink><nav v-if="auth.isAdminSession || auth.isProviderSession" class="nav" :aria-label="isProviderWorkspace ? 'Provider workspace navigation' : 'Administration navigation'"><RouterLink v-for="link in isProviderWorkspace ? providerLinks : links" :key="link.to" :to="link.to" :class="{ active: route.path === link.to || route.path.startsWith(`${link.to}/`) }"><component :is="link.icon" :size="16" />{{ link.label }}</RouterLink></nav><div class="account"><span v-if="auth.isAdminSession || auth.isProviderSession" class="role">{{ isProviderWorkspace ? 'Provider team' : 'Platform admin' }}</span><button v-if="auth.isAdminSession || auth.isProviderSession" type="button" title="Sign out" @click="logout"><LogOut :size="17" /></button><RouterLink v-else class="sign-in" to="/login"><LogIn :size="16" />Sign in</RouterLink></div></el-header>
    <el-main class="content"><RouterView /></el-main>
  </el-container>
</template>

<style scoped>
.shell { background:#f4f7fa; min-height:100vh; }.topbar{align-items:center;background:#14213d;color:#fff;display:flex;gap:22px;height:auto;min-height:64px;padding:0 24px}.brand{color:#fff;font-weight:900;text-decoration:none;white-space:nowrap}.nav{display:flex;flex:1;gap:4px;overflow-x:auto}.nav a,.sign-in{align-items:center;color:#b7c3d8;display:inline-flex;font-size:13px;font-weight:700;gap:7px;padding:9px 10px;text-decoration:none;white-space:nowrap}.nav a:hover,.nav a.active{background:#263b62;color:#fff}.account{align-items:center;display:flex;gap:8px;margin-left:auto}.role{color:#dbeafe;font-size:12px}.account button{align-items:center;background:transparent;border:0;color:#fff;cursor:pointer;display:inline-flex;padding:8px}.account button:focus-visible,.nav a:focus-visible,.sign-in:focus-visible{outline:3px solid #f59e0b;outline-offset:2px}.content{padding:0}@media(max-width:860px){.topbar{align-items:start;flex-wrap:wrap;padding:14px 16px 0}.nav{flex-basis:100%;order:3;padding-bottom:10px}.account{margin-left:auto}.role{display:none}}
</style>
