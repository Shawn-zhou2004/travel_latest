<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CalendarPlus, CircleAlert, ClipboardList, MapPin, PenLine, Plus, RefreshCw } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { normalizeApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { createProviderExperience, createProviderExperienceSession, listProviderExperiences, updateProviderExperience, type ExperienceInput, type ProviderExperience, type ProviderExperienceSession, type SessionInput } from '../services/experiences'

const auth = useAuthStore()
const scopes = computed(() => [...new Set(auth.user?.provider_memberships ?? [])])
const selectedScope = ref(scopes.value.length === 1 ? scopes.value[0] : '')
const experiences = ref<ProviderExperience[]>([])
const loading = ref(false)
const error = ref('')
const experienceDialogOpen = ref(false)
const sessionDialogOpen = ref(false)
const submitting = ref(false)
const editing = ref<ProviderExperience>()
const sessionExperience = ref<ProviderExperience>()
const experienceForm = ref<ExperienceInput>(emptyExperienceForm())
const sessionForm = ref<SessionInput>(emptySessionForm())

const canManage = computed(() => auth.isProviderSession && !auth.isAdminSession && scopes.value.length > 0 && Boolean(selectedScope.value))
const scopeRequired = computed(() => scopes.value.length > 1 && !selectedScope.value)
const scopeDenied = computed(() => !auth.isProviderSession || auth.isAdminSession || scopes.value.length === 0)
const canSaveExperience = computed(() => experienceForm.value.title.trim() && experienceForm.value.description.trim() && experienceForm.value.poi_id.trim() && Number(experienceForm.value.price_amount) > 0 && /^[A-Z]{3}$/.test(experienceForm.value.currency) && experienceForm.value.cancellation_policy.trim())
const canSaveSession = computed(() => Boolean(sessionExperience.value) && Boolean(sessionForm.value.starts_at) && sessionForm.value.capacity > 0 && (!sessionForm.value.price_amount || Number(sessionForm.value.price_amount) > 0) && (!sessionForm.value.price_amount || /^[A-Z]{3}$/.test(sessionForm.value.currency ?? '')))

function emptyExperienceForm(): ExperienceInput {
  return { title: '', description: '', poi_id: '', price_amount: '', currency: 'CNY', cancellation_policy: '', status: 'draft' }
}

function emptySessionForm(): SessionInput {
  return { starts_at: '', capacity: 1, price_amount: null, currency: null }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function statusLabel(status: string) {
  return ({ draft: '草稿', published: '已发布', archived: '已归档', scheduled: '已排期', cancelled: '已取消', completed: '已完成' } as Record<string, string>)[status] ?? status
}

function statusType(status: string) {
  return status === 'published' || status === 'scheduled' ? 'success' : status === 'draft' ? 'warning' : 'info'
}

function clearWorkspace() {
  experiences.value = []
  error.value = ''
}

async function load() {
  if (!canManage.value) return clearWorkspace()
  loading.value = true
  error.value = ''
  try {
    experiences.value = await listProviderExperiences(selectedScope.value)
  } catch (cause) {
    experiences.value = []
    error.value = normalizeApiError(cause).message
  } finally {
    loading.value = false
  }
}

function changeScope() {
  clearWorkspace()
  void load()
}

function openCreate() {
  editing.value = undefined
  experienceForm.value = emptyExperienceForm()
  experienceDialogOpen.value = true
}

function openEdit(experience: ProviderExperience) {
  editing.value = experience
  experienceForm.value = { title: experience.title, description: experience.description, poi_id: experience.poi_id, price_amount: experience.price_amount, currency: experience.currency, cancellation_policy: experience.cancellation_policy, status: experience.status === 'archived' ? 'draft' : experience.status }
  experienceDialogOpen.value = true
}

function openSession(experience: ProviderExperience) {
  sessionExperience.value = experience
  sessionForm.value = emptySessionForm()
  sessionDialogOpen.value = true
}

async function saveExperience() {
  if (!canSaveExperience.value || !selectedScope.value) return
  submitting.value = true
  try {
    if (editing.value) await updateProviderExperience(selectedScope.value, editing.value.id, experienceForm.value)
    else await createProviderExperience(selectedScope.value, experienceForm.value)
    ElMessage.success(editing.value ? '体验服务已更新。' : '体验服务已创建。')
    experienceDialogOpen.value = false
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    submitting.value = false
  }
}

async function saveSession() {
  if (!canSaveSession.value || !selectedScope.value || !sessionExperience.value) return
  submitting.value = true
  try {
    await createProviderExperienceSession(selectedScope.value, sessionExperience.value.id, sessionForm.value)
    ElMessage.success('场次已排期。')
    sessionDialogOpen.value = false
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    submitting.value = false
  }
}

function sessionPrice(session: ProviderExperienceSession, experience: ProviderExperience) {
  return `${session.currency ?? experience.currency} ${session.price_amount ?? experience.price_amount}`
}

onMounted(load)
</script>

<template>
  <main class="provider-page">
    <section class="page-heading">
      <div><h1>体验服务</h1><p>维护本供应商范围内的体验目录与场次。已验证的 POI 仅供查看，预订、旅客和支付不在此工作台处理。</p></div>
      <div class="heading-actions"><button class="icon-action" type="button" title="刷新体验服务" :disabled="loading || !canManage" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button><button class="primary-button" type="button" :disabled="!canManage" @click="openCreate"><Plus :size="18" />新建体验</button></div>
    </section>

    <section class="scope-bar" aria-label="供应商范围">
      <div><strong>当前供应商范围</strong><span>仅请求已明确选择的授权范围。</span></div>
      <el-select v-if="scopes.length > 1" v-model="selectedScope" class="scope-select" placeholder="选择供应商范围" aria-label="选择供应商范围" @change="changeScope"><el-option v-for="scope in scopes" :key="scope" :label="scope" :value="scope" /></el-select>
      <code v-else-if="scopes.length === 1">{{ scopes[0] }}</code>
      <span v-else class="scope-denied-label">未提供供应商范围</span>
    </section>

    <section v-if="scopeDenied" class="state-panel denied"><CircleAlert :size="22" /><div><h2>无法进入供应商工作台</h2><p>此会话未携带 provider_admin 或 provider_staff 角色及可用供应商范围。平台管理操作保持在独立工作台中。</p></div></section>
    <section v-else-if="scopeRequired" class="state-panel"><ClipboardList :size="22" /><div><h2>请选择供应商范围</h2><p>当前会话包含多个授权范围。选择范围后才会加载体验服务，不会根据个人资料或其他信息推断范围。</p></div></section>
    <section v-else class="workspace" aria-label="体验服务列表">
      <div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载体验服务</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div>
      <template v-else>
        <div v-if="loading" class="loading-state">正在加载体验服务…</div>
        <div v-else-if="!experiences.length" class="empty-state"><CalendarPlus :size="28" /><h2>尚未创建体验服务</h2><p>在当前供应商范围内创建第一项服务后，可继续为它安排场次。</p><button class="primary-button" type="button" @click="openCreate"><Plus :size="18" />新建体验</button></div>
        <div v-else class="experience-list"><article v-for="experience in experiences" :key="experience.id" class="experience-row"><div class="service-summary"><div class="title-line"><h2>{{ experience.title }}</h2><el-tag effect="plain" :type="statusType(experience.status)">{{ statusLabel(experience.status) }}</el-tag></div><p>{{ experience.description }}</p><div class="poi"><MapPin :size="16" /><div><strong>{{ experience.poi_name }}</strong><span>{{ experience.poi_address }}</span><code>POI {{ experience.poi_id }}</code></div></div><div class="service-meta"><span>基础价格</span><strong>{{ experience.currency }} {{ experience.price_amount }}</strong><span>取消规则</span><p>{{ experience.cancellation_policy }}</p></div></div><div class="session-area"><div class="session-heading"><strong>场次</strong><button class="text-action" type="button" @click="openSession(experience)"><CalendarPlus :size="16" />安排场次</button></div><div v-if="experience.sessions.length" class="session-list"><div v-for="session in experience.sessions" :key="session.id" class="session"><span>{{ formatDate(session.starts_at) }}</span><span>{{ sessionPrice(session, experience) }}</span><span>容量 {{ session.reserved_count }}/{{ session.capacity }}</span><el-tag size="small" effect="plain" :type="statusType(session.status)">{{ statusLabel(session.status) }}</el-tag></div></div><p v-else class="no-sessions">尚未安排场次。</p></div><div class="row-actions"><button class="text-action" type="button" @click="openEdit(experience)"><PenLine :size="16" />编辑</button></div></article></div>
      </template>
    </section>

    <el-dialog v-model="experienceDialogOpen" :title="editing ? '编辑体验服务' : '新建体验服务'" width="min(680px, calc(100% - 32px))" destroy-on-close><form class="form-grid" @submit.prevent="saveExperience"><label>体验名称<el-input v-model="experienceForm.title" maxlength="160" /></label><label>状态<el-select v-model="experienceForm.status"><el-option label="草稿" value="draft" /><el-option label="发布" value="published" /></el-select></label><label class="full">体验说明<el-input v-model="experienceForm.description" type="textarea" :rows="4" /></label><label class="full">已验证 POI 标识<el-input v-model="experienceForm.poi_id" maxlength="128" :disabled="Boolean(editing)" /><small>{{ editing ? 'POI 一经验证不可在此编辑。' : '保存后由服务端验证并以只读方式显示名称与地址。' }}</small></label><label>基础价格<el-input v-model="experienceForm.price_amount" inputmode="decimal" placeholder="0.00" /></label><label>币种<el-input v-model="experienceForm.currency" maxlength="3" @input="experienceForm.currency = experienceForm.currency.toUpperCase()" /></label><label class="full">取消规则<el-input v-model="experienceForm.cancellation_policy" type="textarea" :rows="3" /></label><div class="dialog-actions full"><button class="secondary-button" type="button" @click="experienceDialogOpen = false">取消</button><button class="primary-button" type="submit" :disabled="!canSaveExperience || submitting">{{ submitting ? '保存中…' : '保存体验服务' }}</button></div></form></el-dialog>
    <el-dialog v-model="sessionDialogOpen" title="安排场次" width="min(520px, calc(100% - 32px))" destroy-on-close><form class="form-grid" @submit.prevent="saveSession"><p class="full dialog-copy">{{ sessionExperience?.title }}</p><label class="full">开始时间<el-date-picker v-model="sessionForm.starts_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" /></label><label>容量<el-input-number v-model="sessionForm.capacity" :min="1" :max="1000" controls-position="right" /></label><label>覆盖价格（可选）<el-input v-model="sessionForm.price_amount" inputmode="decimal" placeholder="沿用基础价格" /></label><label class="full">覆盖币种（填写覆盖价格时必填）<el-input v-model="sessionForm.currency" maxlength="3" @input="sessionForm.currency = sessionForm.currency?.toUpperCase() ?? null" /></label><div class="dialog-actions full"><button class="secondary-button" type="button" @click="sessionDialogOpen = false">取消</button><button class="primary-button" type="submit" :disabled="!canSaveSession || submitting">{{ submitting ? '保存中…' : '安排场次' }}</button></div></form></el-dialog>
  </main>
</template>

<style scoped>
.provider-page{margin:0 auto;max-width:1440px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;gap:24px;justify-content:space-between;margin-bottom:22px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;line-height:1.55;margin:0;max-width:760px}.heading-actions{display:flex;gap:10px}.icon-action,.primary-button,.secondary-button{align-items:center;border-radius:6px;cursor:pointer;display:inline-flex;font-weight:700;justify-content:center}.icon-action{background:#fff;border:1px solid #cbd5d9;color:#142638;height:38px;width:38px}.primary-button{background:#167a76;border:1px solid #167a76;color:#fff;gap:7px;min-height:38px;padding:0 14px}.secondary-button{background:#fff;border:1px solid #aebec3;color:#27404c;min-height:38px;padding:0 14px}.icon-action:disabled,.primary-button:disabled{cursor:not-allowed;opacity:.55}.scope-bar{align-items:center;background:#edf3f1;border:1px solid #d7e0df;display:flex;gap:20px;justify-content:space-between;margin-bottom:20px;min-height:66px;padding:10px 20px}.scope-bar div{display:grid;gap:3px}.scope-bar strong{color:#142638}.scope-bar span{color:#5e6b74;font-size:13px}.scope-bar code,.scope-denied-label{background:#fff;border:1px solid #c9d8d4;color:#27404c;font:12px ui-monospace,monospace;padding:8px 10px}.scope-select{width:min(380px,100%)}.workspace{background:#fff;border:1px solid #d7e0df;min-height:320px}.state-panel,.error-state{align-items:flex-start;background:#fff;display:flex;gap:14px;margin:0 auto;max-width:820px;padding:48px 24px}.state-panel{margin-top:42px}.state-panel h2,.empty-state h2{color:#142638;font-size:20px;margin:0 0 7px}.state-panel p,.error-state p,.empty-state p{color:#5e6b74;line-height:1.55;margin:0}.denied{color:#9f392b}.loading-state,.empty-state{color:#667680;padding:64px 24px;text-align:center}.empty-state{align-items:center;display:flex;flex-direction:column;gap:11px}.error-state{background:#fff5f2;color:#9f392b;margin:20px;padding:18px}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.experience-list{display:grid}.experience-row{border-bottom:1px solid #d7e0df;display:grid;grid-template-columns:minmax(0,1fr) 340px 88px;padding:22px 24px}.experience-row:last-child{border-bottom:0}.service-summary{min-width:0;padding-right:28px}.title-line{align-items:center;display:flex;gap:10px}.title-line h2{color:#142638;font-size:18px;margin:0}.service-summary>p{color:#53656f;line-height:1.5;margin:10px 0 16px}.poi{align-items:flex-start;background:#f3f7f5;border:1px solid #d7e0df;color:#167a76;display:flex;gap:8px;padding:10px 12px}.poi div{display:grid;gap:3px}.poi strong{color:#27404c;font-size:13px}.poi span{color:#62747d;font-size:12px}.poi code{color:#62747d;font:11px ui-monospace,monospace}.service-meta{border-left:1px solid #d7e0df;display:grid;gap:4px;padding:0 22px}.service-meta span{color:#77878f;font-size:12px;margin-top:4px}.service-meta strong{color:#142638}.service-meta p{color:#53656f;font-size:13px;line-height:1.4;margin:0}.session-area{border-top:1px solid #d7e0df;grid-column:1/3;margin-top:18px;padding-top:14px}.session-heading{align-items:center;display:flex;justify-content:space-between}.text-action{align-items:center;background:none;border:0;color:#167a76;cursor:pointer;display:inline-flex;font-size:13px;font-weight:700;gap:4px;padding:4px 0}.session-list{display:grid;gap:6px;margin-top:10px}.session{align-items:center;background:#f8faf9;color:#40545d;display:grid;font-size:13px;gap:10px;grid-template-columns:1.4fr 1fr 1fr auto;padding:9px 10px}.no-sessions{color:#77878f;font-size:13px;margin:10px 0 0}.row-actions{align-items:start;display:flex;justify-content:flex-end}.form-grid{display:grid;gap:16px;grid-template-columns:1fr 1fr}.form-grid label{color:#354a55;display:grid;font-size:13px;font-weight:700;gap:7px}.form-grid .full{grid-column:1/-1}.form-grid small{color:#6b7d86;font-size:12px;font-weight:400}.dialog-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:8px}.dialog-copy{color:#53656f;margin:0}.icon-action:focus-visible,.primary-button:focus-visible,.secondary-button:focus-visible,.text-action:focus-visible{outline:3px solid #d99824;outline-offset:2px}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:860px){.provider-page{padding:28px 18px 42px}.page-heading{flex-direction:column}.heading-actions{width:100%}.scope-bar{align-items:flex-start;flex-direction:column}.scope-select{width:100%}.experience-row{grid-template-columns:1fr;padding:20px 16px}.service-summary{padding-right:0}.service-meta{border-left:0;border-top:1px solid #d7e0df;margin-top:16px;padding:14px 0 0}.session-area{grid-column:auto}.row-actions{margin-top:14px}.session{grid-template-columns:1fr 1fr}.form-grid{grid-template-columns:1fr}.form-grid .full{grid-column:auto}}@media(prefers-reduced-motion:reduce){.spinning{animation:none}}
</style>
