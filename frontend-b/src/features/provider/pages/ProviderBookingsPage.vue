<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BadgeCheck, CircleAlert, ClipboardCheck, RefreshCw } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { useAuthStore } from '@/stores/auth'
import { normalizeApiError } from '@/services/api'
import { listProviderBookings, verifyProviderBooking, type ProviderBooking } from '../services/experiences'

const auth = useAuthStore()
const scopes = computed(() => [...new Set(auth.user?.provider_memberships ?? [])])
const selectedScope = ref(scopes.value.length === 1 ? scopes.value[0] : '')
const bookings = ref<ProviderBooking[]>([])
const loading = ref(false)
const verifyingId = ref('')
const codeByBooking = ref<Record<string, string>>({})
const error = ref('')
const canManage = computed(() => auth.isProviderSession && !auth.isAdminSession && Boolean(selectedScope.value))

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

async function load() {
  if (!canManage.value) { bookings.value = []; return }
  loading.value = true
  error.value = ''
  try { bookings.value = await listProviderBookings(selectedScope.value) }
  catch (cause) { bookings.value = []; error.value = normalizeApiError(cause).message }
  finally { loading.value = false }
}

async function verify(booking: ProviderBooking) {
  const code = codeByBooking.value[booking.id]?.trim()
  if (!code || verifyingId.value) return
  verifyingId.value = booking.id
  try {
    await verifyProviderBooking(selectedScope.value, booking.id, code)
    delete codeByBooking.value[booking.id]
    ElMessage.success('预订已核销。')
    await load()
  } catch (cause) { ElMessage.error(normalizeApiError(cause).message) }
  finally { verifyingId.value = '' }
}

function changeScope() { bookings.value = []; error.value = ''; void load() }
onMounted(load)
</script>

<template>
  <main class="booking-page">
    <header class="page-heading"><div><p class="eyebrow">ON-SITE / VERIFICATION</p><h1>预订核销</h1><p>仅处理当前供应商范围内待到店的预订。旅客提供核销码后，状态会立即变更且不能重复核销。</p></div><button class="icon-action" type="button" title="刷新待核销预订" :disabled="loading || !canManage" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button></header>
    <section class="scope-bar"><div><strong>当前供应商范围</strong><span>不会根据体验或预订记录推断其他范围。</span></div><el-select v-if="scopes.length > 1" v-model="selectedScope" placeholder="选择供应商范围" aria-label="选择供应商范围" @change="changeScope"><el-option v-for="scope in scopes" :key="scope" :label="scope" :value="scope" /></el-select><code v-else-if="selectedScope">{{ selectedScope }}</code><span v-else class="scope-empty">未提供供应商范围</span></section>
    <section v-if="!canManage" class="state-panel"><CircleAlert :size="22" /><div><h2>无法加载预订</h2><p>此会话没有可用的服务商范围。请使用具备 provider_admin 或 provider_staff 角色的账号。</p></div></section>
    <section v-else class="booking-board" aria-label="待核销预订"><div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载待核销预订</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div><p v-else-if="loading" class="loading-state">正在加载待核销预订…</p><div v-else-if="!bookings.length" class="empty-state"><ClipboardCheck :size="30" /><h2>当前没有待核销预订</h2><p>新的已预订场次会显示在这里，核销后将从待处理列表移出。</p></div><article v-for="booking in bookings" v-else :key="booking.id" class="booking-row"><div class="booking-date"><span>{{ formatDate(booking.starts_at) }}</span><small>{{ booking.traveler_count }} 位旅客</small></div><div class="booking-main"><strong>{{ booking.experience_title }}</strong><span>状态：待核销</span></div><form class="verify-form" @submit.prevent="verify(booking)"><label>旅客核销码<input v-model="codeByBooking[booking.id]" autocomplete="off" maxlength="24" :disabled="verifyingId === booking.id" /></label><button class="verify-button" type="submit" :disabled="!codeByBooking[booking.id]?.trim() || Boolean(verifyingId)"><BadgeCheck :size="16" />{{ verifyingId === booking.id ? '核销中…' : '确认核销' }}</button></form></article></section>
  </main>
</template>

<style scoped>
.booking-page{margin:0 auto;max-width:1180px;padding:38px 42px 56px}.page-heading{align-items:flex-start;border-bottom:2px solid #167a76;display:flex;justify-content:space-between;gap:24px;padding-bottom:20px}.eyebrow{color:#167a76;font:800 11px ui-monospace,monospace;letter-spacing:.08em;margin:0 0 8px}.page-heading h1{color:#142638;font-size:30px;letter-spacing:0;margin:0}.page-heading p:last-child{color:#5e6b74;line-height:1.55;margin:9px 0 0;max-width:700px}.icon-action,.verify-button{align-items:center;border-radius:6px;cursor:pointer;display:inline-flex;font-weight:700;justify-content:center}.icon-action{background:#fff;border:1px solid #cbd5d9;color:#142638;height:38px;width:38px}.icon-action:disabled,.verify-button:disabled{cursor:not-allowed;opacity:.55}.scope-bar{align-items:center;background:#edf3f1;border:1px solid #d7e0df;display:flex;gap:20px;justify-content:space-between;margin:20px 0;min-height:66px;padding:10px 20px}.scope-bar div{display:grid;gap:3px}.scope-bar span{color:#5e6b74;font-size:13px}.scope-bar code,.scope-empty{background:#fff;border:1px solid #c9d8d4;color:#27404c;font:12px ui-monospace,monospace;padding:8px 10px}.scope-bar :deep(.el-select){width:min(380px,100%)}.booking-board{background:#fff;border:1px solid #d7e0df}.booking-row{align-items:center;border-bottom:1px solid #e2e8e6;display:grid;gap:18px;grid-template-columns:200px minmax(0,1fr) minmax(280px,.9fr);padding:18px 20px}.booking-row:last-child{border-bottom:0}.booking-date,.booking-main{display:grid;gap:5px}.booking-date span,.booking-main strong{color:#142638;font-weight:800}.booking-date small,.booking-main span{color:#667680;font-size:13px}.verify-form{align-items:end;display:grid;gap:8px;grid-template-columns:minmax(0,1fr) auto}.verify-form label{color:#53636b;display:grid;font-size:12px;font-weight:700;gap:5px}.verify-form input{border:1px solid #b8c8c5;min-height:38px;padding:0 9px}.verify-button{background:#167a76;border:1px solid #167a76;color:#fff;gap:6px;min-height:38px;padding:0 12px}.state-panel,.error-state,.empty-state,.loading-state{padding:42px 24px}.state-panel,.error-state{align-items:flex-start;display:flex;gap:12px}.state-panel,.empty-state,.loading-state{background:#fff;border:1px solid #d7e0df}.state-panel h2,.empty-state h2{color:#142638;font-size:19px;margin:0 0 6px}.state-panel p,.empty-state p,.error-state p{color:#5e6b74;line-height:1.55;margin:0}.error-state{background:#fff5f2;color:#9f392b}.error-state button{margin-left:auto}.empty-state{align-items:center;display:flex;flex-direction:column;gap:9px;text-align:center}.loading-state{color:#667680}.spinning{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.booking-page{padding:28px 18px 48px}.scope-bar,.page-heading{align-items:stretch;flex-direction:column}.booking-row{grid-template-columns:1fr}.verify-form{grid-template-columns:1fr}.verify-button{width:100%}}
</style>
