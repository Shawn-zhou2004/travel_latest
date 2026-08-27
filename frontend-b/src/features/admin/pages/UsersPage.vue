<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CircleAlert, RefreshCw, Search, Users } from 'lucide-vue-next'
import { normalizeApiError } from '@/services/api'
import { listAdminUsers, updateAdminUser, type AdminUser } from '../services/users'

const users = ref<AdminUser[]>([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const nextCursor = ref<string | null>(null)
const updatingUserId = ref<string | null>(null)

function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function roleLabel(role: string) { return ({ platform_admin: '平台管理员', provider_admin: '供应商管理员', provider_staff: '供应商员工', user: '用户' } as Record<string, string>)[role] ?? role }
async function load(cursor?: string) {
  loading.value = true
  error.value = ''
  try {
    const page = await listAdminUsers({ query: query.value.trim() || undefined, limit: 50, cursor })
    users.value = cursor ? [...users.value, ...page.items] : page.items
    nextCursor.value = page.next_cursor
  } catch (cause) {
    if (!cursor) users.value = []
    error.value = normalizeApiError(cause).message
  } finally { loading.value = false }
}
function search() { nextCursor.value = null; void load() }
async function toggleStatus(user: AdminUser) {
  updatingUserId.value = user.id
  error.value = ''
  try {
    const updated = await updateAdminUser(user.id, { status: user.status === 'active' ? 'suspended' : 'active' })
    users.value = users.value.map((item) => item.id === user.id ? updated : item)
  } catch (cause) {
    error.value = normalizeApiError(cause).message
  } finally { updatingUserId.value = null }
}
onMounted(() => void load())
</script>

<template>
  <main class="users-page">
    <header class="page-heading"><div><p class="eyebrow">ACCOUNT DIRECTORY</p><h1>用户目录</h1><p>可暂停或恢复账户。角色和供应商范围仅供查看，避免在缺少供应商范围参数时改变已有授权。</p></div><button class="icon-action" type="button" title="刷新用户目录" :disabled="loading" @click="load()"><RefreshCw :size="18" :class="{ spinning: loading }" /></button></header>
    <form class="search-bar" role="search" @submit.prevent="search"><Search :size="18" /><input v-model="query" aria-label="搜索用户" placeholder="搜索手机号或昵称" maxlength="200" /><button type="submit" :disabled="loading">搜索</button></form>
    <div v-if="error" class="error-state" role="alert"><CircleAlert :size="20" /><div><strong>无法加载用户目录</strong><p>{{ error }}</p></div><button type="button" @click="load()">重新尝试</button></div>
    <div v-else-if="!loading && !users.length" class="empty-state"><Users :size="28" /><strong>暂无用户</strong><p>{{ query ? '没有匹配当前搜索条件的用户。' : '平台还没有可供查看的用户记录。' }}</p></div>
    <section v-else class="directory" aria-label="用户目录" :aria-busy="loading">
      <div class="directory-head"><span>账户</span><span>角色</span><span>供应商范围</span><span>状态</span><span>最近更新</span></div>
      <article v-for="user in users" :key="user.id" class="user-row"><div class="identity"><strong>{{ user.nickname || '未设置昵称' }}</strong><code>{{ user.phone_masked }}</code><small>{{ user.id }}</small></div><div class="roles"><span v-for="role in user.roles" :key="role" class="tag">{{ roleLabel(role) }}</span><span v-if="!user.roles.length" class="muted">无角色</span></div><div class="memberships"><code v-for="membership in user.provider_memberships" :key="membership">{{ membership }}</code><span v-if="!user.provider_memberships.length" class="muted">无供应商范围</span></div><div class="status-control"><span class="status-tag" :class="{ suspended: user.status === 'suspended' }">{{ user.status === 'active' ? '活跃' : '已暂停' }}</span><button type="button" :disabled="updatingUserId === user.id" @click="toggleStatus(user)">{{ updatingUserId === user.id ? '更新中…' : user.status === 'active' ? '暂停' : '恢复' }}</button></div><div class="dates"><span>创建 {{ formatDate(user.created_at) }}</span><span>更新 {{ formatDate(user.updated_at) }}</span></div></article>
      <button v-if="nextCursor" class="load-more" type="button" :disabled="loading" @click="load(nextCursor ?? undefined)">{{ loading ? '加载中…' : '加载更多' }}</button>
    </section>
  </main>
</template>

<style scoped>
.status-control{display:grid;gap:7px}.status-control button{background:#fff;border:1px solid #cbd5d9;border-radius:4px;color:#27404c;cursor:pointer;font:inherit;font-size:12px;font-weight:700;padding:5px}.status-control button:disabled{cursor:not-allowed;opacity:.55}.status-tag.suspended{background:#fff2ee;border-color:#e3b4a9;color:#a84734}
.users-page{margin:0 auto;max-width:1280px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:26px}.page-heading h1{color:#142638;font-size:28px;margin:0 0 8px}.page-heading p{color:#5e6b74;margin:0;line-height:1.5}.eyebrow{color:#167a76!important;font-size:11px!important;font-weight:800;letter-spacing:1.4px;margin:0 0 8px!important}.icon-action{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;height:38px;justify-content:center;width:38px}.icon-action:disabled,.search-bar button:disabled,.load-more:disabled{cursor:not-allowed;opacity:.55}.search-bar{align-items:center;background:#fff;border:1px solid #cbd5d9;display:flex;gap:10px;margin-bottom:18px;max-width:640px;padding:8px 10px;color:#64737d}.search-bar input{border:0;color:#142638;flex:1;font:inherit;min-width:0;outline:0}.search-bar button,.load-more{background:#167a76;border:1px solid #167a76;border-radius:5px;color:#fff;cursor:pointer;font-weight:700;padding:8px 14px}.directory{background:#fff;border:1px solid #d7e0df}.directory-head,.user-row{display:grid;gap:18px;grid-template-columns:1.4fr 1.1fr 1.1fr 70px 1.3fr;padding:16px 20px}.directory-head{background:#edf3f1;color:#64737d;font-size:12px;font-weight:800}.user-row{align-items:center;border-top:1px solid #e3eae8;color:#27404c;font-size:13px}.identity strong,.identity code,.identity small{display:block}.identity strong{color:#142638;font-size:15px}.identity code,.memberships code{color:#167a76;font:12px ui-monospace,monospace;margin-top:5px}.identity small{color:#9aa8ad;font-size:11px;margin-top:5px;overflow:hidden;text-overflow:ellipsis}.roles,.memberships{display:flex;flex-wrap:wrap;gap:5px}.tag,.status-tag{border:1px solid #c9d8d4;border-radius:4px;color:#167a76;font-size:12px;padding:4px 7px}.status-tag{background:#edf8f1;border-color:#a8d9b7;color:#24743d;text-align:center}.muted{color:#829099;font-size:12px}.dates{color:#64737d;display:grid;gap:4px;font-size:12px}.load-more{display:block;margin:18px auto}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{align-items:center;background:#fff;border:1px solid #d7e0df;color:#64737d;display:flex;flex-direction:column;gap:10px;padding:64px;text-align:center}.empty-state strong{color:#142638}.empty-state p{margin:0}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:820px){.users-page{padding:28px 16px 44px}.directory{overflow-x:auto}.directory-head,.user-row{min-width:840px}.page-heading{gap:16px}.page-heading h1{font-size:24px}}
</style>
