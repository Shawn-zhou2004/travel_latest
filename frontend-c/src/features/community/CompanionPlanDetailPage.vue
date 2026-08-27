<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, Check, CircleAlert, DoorOpen, MessageCircle, Pencil, RefreshCw, Route, Send, Users, X } from 'lucide-vue-next'
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ImageReferenceUpload from '@/features/media/components/ImageReferenceUpload.vue'
import CompanionPlanTimeline from './components/CompanionPlanTimeline.vue'
import { acceptCompanionApplication, acceptedDestination, applyToCompanionPlan, cancelCompanionPlan, closeCompanionPlan, companionInterestTags, completeCompanionPlan, getCompanionPlan, leaveCompanionPlan, listCompanionPlanApplications, listMyCompanionApplications, rejectCompanionApplication, removeCompanionMember, reopenCompanionPlan, updateCompanionPlan, withdrawCompanionApplication, type CompanionApplication, type CompanionPace, type CompanionPlanDetail } from './companionPlansApi'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ requestId: string }>()
const router = useRouter()
const auth = useAuthStore()
const plan = ref<CompanionPlanDetail>()
const applications = ref<CompanionApplication[]>([])
const message = ref('')
const loading = ref(true)
const busy = ref(false)
const editing = ref(false)
const error = ref('')
const notice = ref('')
const groupProfileOpen = ref(false)
const groupProfileError = ref('')
const selectedApplicationId = ref('')
const groupProfile = ref({ name: '', avatarAssetId: '' })
const root = ref<HTMLElement | null>(null)
useReveal(root)
const form = ref({
  title: '',
  cityCode: '',
  partySize: 2,
  budgetMin: null as number | null,
  budgetMax: null as number | null,
  currency: 'CNY',
  pace: 'balanced' as CompanionPace,
  tags: [] as string[],
  intro: '',
})
const isProtectedMember = computed(() => ['owner', 'member'].includes(plan.value?.viewer_role ?? ''))
const isOwner = computed(() => plan.value?.viewer_role === 'owner')
const isAcceptedMember = computed(() => plan.value?.viewer_role === 'member')
const pendingApplication = computed(() => plan.value?.application_status === 'pending')
const pendingApplications = computed(() => applications.value.filter((application) => application.status === 'pending'))
const isOpenNonOwner = computed(() => plan.value?.status === 'open' && !isOwner.value && !isAcceptedMember.value)
const canApply = computed(() => auth.isConsumerSession && isOpenNonOwner.value && ['rejected', 'withdrawn', null].includes(plan.value?.application_status ?? null))
const needsLoginToApply = computed(() => !auth.isConsumerSession && isOpenNonOwner.value)
const canEditMetadata = computed(() => isOwner.value && !['cancelled', 'completed'].includes(plan.value?.status ?? ''))
const canManageLifecycle = computed(() => isOwner.value && plan.value?.review_status === 'approved')
const editInvalid = computed(() => !plan.value || !form.value.title.trim() || form.value.partySize < plan.value.accepted_count || form.value.partySize > 12 || !form.value.intro.trim() || form.value.tags.length === 0 || form.value.tags.length > 8 || (form.value.budgetMin === null) !== (form.value.budgetMax === null) || (form.value.budgetMin !== null && form.value.budgetMax !== null && form.value.budgetMin > form.value.budgetMax))

function syncForm(value: CompanionPlanDetail) {
  form.value = {
    title: value.title,
    cityCode: value.city_code ?? '',
    partySize: value.party_size ?? value.accepted_count,
    budgetMin: value.budget_min === null ? null : Number(value.budget_min),
    budgetMax: value.budget_max === null ? null : Number(value.budget_max),
    currency: value.currency ?? 'CNY',
    pace: value.travel_pace ?? 'balanced',
    tags: [...value.interest_tags],
    intro: value.intro_text ?? '',
  }
}

async function loadPlan() {
  loading.value = true
  error.value = ''
  try {
    plan.value = await getCompanionPlan(props.requestId)
    syncForm(plan.value)
    applications.value = isOwner.value ? await listCompanionPlanApplications(props.requestId) : plan.value.application_status === 'pending' ? (await listMyCompanionApplications()).filter((application) => application.request_id === props.requestId) : []
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '同行计划暂时无法读取。'
  } finally {
    loading.value = false
  }
}

async function runAction(action: () => Promise<unknown>, success: string) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
    notice.value = success
    await loadPlan()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '操作未完成，请稍后重试。'
  } finally {
    busy.value = false
  }
}

function toggleTag(tag: string) {
  form.value.tags = form.value.tags.includes(tag) ? form.value.tags.filter((item) => item !== tag) : form.value.tags.length < 8 ? [...form.value.tags, tag] : form.value.tags
}

function saveMetadata() {
  if (editInvalid.value) return
  void runAction(async () => {
    await updateCompanionPlan(props.requestId, {
      title: form.value.title.trim(),
      city_code: form.value.cityCode.trim() || null,
      party_size: form.value.partySize,
      budget_min: form.value.budgetMin,
      budget_max: form.value.budgetMax,
      currency: form.value.budgetMin === null ? null : form.value.currency,
      travel_pace: form.value.pace,
      interest_tags: form.value.tags,
      intro_text: form.value.intro.trim(),
    })
    editing.value = false
  }, '同行计划信息已更新。')
}

function apply() {
  if (!auth.isConsumerSession) {
    void router.push({
      path: '/login',
      query: { redirect: `/companions/${props.requestId}` },
    })
    return
  }
  if (!message.value.trim()) {
    error.value = '请先写下你的同行说明。'
    return
  }
  void runAction(() => applyToCompanionPlan(props.requestId, message.value.trim()), '申请已提交，等待发起人确认。')
}

function accept(applicationId: string) {
  if (!plan.value?.conversation_id) {
    selectedApplicationId.value = applicationId
    groupProfileError.value = ''
    groupProfileOpen.value = true
    return
  }
  void acceptWithProfile(applicationId)
}

function submitFirstAcceptance() {
  if (!groupProfile.value.name.trim()) {
    groupProfileError.value = '请填写群聊名称。'
    return
  }
  if (!groupProfile.value.avatarAssetId) {
    groupProfileError.value = '请先上传群头像。'
    return
  }
  void acceptWithProfile(selectedApplicationId.value)
}

async function acceptWithProfile(applicationId: string) {
  void runAction(async () => {
    const result = plan.value?.conversation_id
      ? await acceptCompanionApplication(applicationId)
      : await acceptCompanionApplication(applicationId, groupProfile.value.name.trim(), groupProfile.value.avatarAssetId)
    groupProfileOpen.value = false
    await router.push(acceptedDestination(result))
  }, '成员已加入同行计划。')
}

function remove(application: CompanionApplication) {
  void runAction(() => removeCompanionMember(props.requestId, application.applicant_id), '成员已移出同行计划。')
}
function applicationStatusLabel(status: CompanionApplication['status']) {
  return {
    pending: '待处理',
    accepted: '已接受',
    rejected: '已拒绝',
    withdrawn: '已撤回',
  }[status]
}
function planStatusLabel(status: CompanionPlanDetail['status']) {
  return {
    open: '招募中',
    full: '已满员',
    closed: '已结束招募',
    cancelled: '已取消',
    completed: '已完成',
  }[status]
}
onMounted(loadPlan)
</script>

<template>
  <main class="detail-page" aria-label="同行计划详情" ref="root">
    <RouterLink class="back" to="/companions"><ArrowLeft :size="16" />返回同行计划</RouterLink>
    <section v-if="loading" class="state-panel" aria-live="polite">正在读取同行计划...</section>
    <section v-else-if="error && !plan" class="state-panel" role="alert"><strong>{{ error }}</strong><button type="button" @click="loadPlan"><RefreshCw :size="16" />重试</button></section>
    <template v-else-if="plan">
      <header class="plan-header" data-reveal><p>FIELD / TRAVEL · {{ plan.trip_kind === 'activity' ? 'SHORT ACTIVITY' : 'COMPANION ROUTE' }}</p><h1>{{ plan.title }}</h1><div class="summary"><span>{{ plan.city_code || '目的地待定' }}</span><span>{{ plan.start_date || '日期待定' }}<template v-if="plan.end_date && plan.end_date !== plan.start_date"> - {{ plan.end_date }}</template></span><span>{{ plan.accepted_count }} / {{ plan.party_size ?? '-' }} 人</span><span>{{ planStatusLabel(plan.status) }}</span></div></header>
      <Transition name="fade"><p v-if="notice" class="notice"><Check :size="16" />{{ notice }}</p></Transition>
      <Transition name="fade"><p v-if="error" class="notice error" role="alert"><CircleAlert :size="16" />{{ error }}</p></Transition>
      <div class="detail-grid" data-reveal>
        <div class="reading-column">
          <section class="intro"><p class="section-label">发起人的同行说明</p><p>{{ plan.intro_text || '路线说明正在整理中。' }}</p></section>
          <CompanionPlanTimeline :route-count="plan.route_count" :itinerary="plan.protected_itinerary" />
          <section class="safety"><CircleAlert :size="18" /><div><strong>出发前保持沟通边界</strong><p>公开页面只展示路线概览。具体集合信息与协作路线仅对已加入成员开放。</p></div></section>
          <section v-if="isProtectedMember" class="members"><div class="section-heading"><Users :size="18" /><h2>同行成员</h2></div><ul><li v-for="member in plan.members" :key="`${member.role}-${member.display_name}`"><span class="avatar">{{ member.display_name?.slice(0, 1) || '旅' }}</span><strong>{{ member.display_name || '同行成员' }}</strong><small>{{ member.role === 'owner' ? '发起人' : '成员' }}</small></li></ul></section>
          <section v-if="isOwner" class="applications"><div class="section-heading"><Users :size="18" /><h2>待处理申请（{{ pendingApplications.length }}）</h2></div><p v-if="!applications.length" class="muted">暂时没有申请。</p><article v-for="application in applications" :key="application.id"><div class="application-copy"><div class="application-title"><strong>{{ application.applicant_display_name || '申请人' }}</strong><span>{{ applicationStatusLabel(application.status) }}</span></div><p>{{ application.message }}</p></div><div class="application-actions"><button v-if="application.status === 'pending'" type="button" :disabled="busy" @click="accept(application.id)">接受</button><button v-if="application.status === 'pending'" type="button" :disabled="busy" @click="runAction(() => rejectCompanionApplication(application.id), '申请已拒绝。')">拒绝</button><button v-if="application.status === 'accepted'" type="button" :disabled="busy" @click="remove(application)">移除成员</button></div></article></section>
        </div>
        <aside class="action-rail">
          <section v-if="canApply" class="action-panel"><p class="section-label">申请同行</p><h2>留下你的同行说明</h2><textarea v-model="message" maxlength="1000" placeholder="介绍你的旅行节奏、兴趣或期待。" /><button type="button" :disabled="busy || !message.trim()" @click="apply"><Send :size="16" />发送申请</button></section>
          <section v-else-if="needsLoginToApply" class="action-panel"><p class="section-label">申请同行</p><h2>登录后加入这段同行</h2><p>登录后可以填写同行说明并向发起人提交申请。</p><button type="button" @click="apply"><Send :size="16" />登录并申请</button></section>
          <section v-else-if="pendingApplication" class="action-panel"><p class="section-label">申请状态</p><h2>申请已提交</h2><p>发起人确认前，具体集合信息与协作路线不会显示。</p><button type="button" :disabled="busy" @click="runAction(async () => { const app = applications[0]; if (!app) throw new Error('申请记录暂不可用。'); await withdrawCompanionApplication(app.id) }, '申请已撤回。')"><X :size="16" />撤回申请</button></section>
          <section v-else-if="isAcceptedMember" class="action-panel"><p class="section-label">同行协作</p><h2>你已加入路线</h2><button v-if="plan.conversation_id" type="button" @click="router.push(`/messages/${plan.conversation_id}`)"><MessageCircle :size="16" />进入同行群聊</button><button v-if="plan.itinerary_id" class="secondary" type="button" @click="router.push(`/itineraries/${plan.itinerary_id}`)"><Route :size="16" />查看协作路线</button><button class="quiet" type="button" :disabled="busy" @click="runAction(() => leaveCompanionPlan(plan!.id), '你已退出同行计划。')"><DoorOpen :size="16" />退出同行</button></section>
           <section v-else-if="isOwner" class="action-panel">
            <p class="section-label">发起人控制</p><h2>管理同行状态</h2>
            <button v-if="canEditMetadata" type="button" class="secondary" :disabled="busy" @click="editing = !editing"><Pencil :size="16" />{{ editing ? '收起编辑' : '编辑公开信息' }}</button>
            <Transition name="slide-down"><form v-if="editing && canEditMetadata" class="metadata-form" @submit.prevent="saveMetadata"><label>标题<input v-model="form.title" maxlength="200" required></label><label>城市代码<input v-model="form.cityCode" maxlength="32"></label><label>同行人数<input v-model.number="form.partySize" type="number" :min="plan.accepted_count" max="12" required><small>当前已确认 {{ plan.accepted_count }} 人。</small></label><div class="budget"><label>预算下限<input v-model.number="form.budgetMin" type="number" min="0"></label><label>预算上限<input v-model.number="form.budgetMax" type="number" min="0"></label></div><label>币种<input v-model="form.currency" maxlength="3" :disabled="form.budgetMin === null"></label><label>出行节奏<select v-model="form.pace"><option value="slow">慢行</option><option value="balanced">均衡</option><option value="packed">紧凑</option></select></label><fieldset><legend>兴趣标签</legend><label v-for="tag in companionInterestTags" :key="tag"><input type="checkbox" :checked="form.tags.includes(tag)" @change="toggleTag(tag)">{{ tag }}</label></fieldset><label>同行说明<textarea v-model="form.intro" rows="5" maxlength="2000" required></textarea></label><button type="submit" :disabled="busy || editInvalid"><Check :size="16" />保存公开信息</button></form></Transition>
            <button v-if="canManageLifecycle && plan.status === 'open'" type="button" :disabled="busy" @click="runAction(() => closeCompanionPlan(plan!.id), '招募已关闭。')">关闭招募</button>
            <button v-if="canManageLifecycle && plan.status === 'closed'" type="button" :disabled="busy" @click="runAction(() => reopenCompanionPlan(plan!.id), '招募已重新开放。')">重新开放</button>
            <button v-if="canManageLifecycle && (plan.status === 'open' || plan.status === 'closed')" class="quiet" type="button" :disabled="busy" @click="runAction(() => cancelCompanionPlan(plan!.id), '同行计划已取消。')">取消计划</button>
            <button v-if="canManageLifecycle && plan.status !== 'completed'" class="secondary" type="button" :disabled="busy" @click="runAction(() => completeCompanionPlan(plan!.id), '同行计划已完成。')">完成计划</button>
           </section>
           <Transition name="fade"><section v-if="groupProfileOpen" class="action-panel group-profile" aria-labelledby="group-profile-title"><p class="section-label">首次创建同行群聊</p><h2 id="group-profile-title">设置群聊资料</h2><label>群名称<input v-model="groupProfile.name" maxlength="200" placeholder="例如：西湖慢行小组" /></label><p v-if="!groupProfile.name.trim()" class="form-error">请填写群聊名称后继续。</p><ImageReferenceUpload @completed="groupProfile.avatarAssetId = $event" /><p v-if="!groupProfile.avatarAssetId" class="form-error">请上传群头像后继续。</p><p v-else role="status">群头像已上传。</p><p v-if="groupProfileError" class="form-error" role="alert">{{ groupProfileError }}</p><div class="group-profile-actions"><button type="button" @click="groupProfileOpen = false">取消</button><button type="button" :disabled="busy || !groupProfile.name.trim() || !groupProfile.avatarAssetId" @click="submitFirstAcceptance">确认并接受</button></div></section></Transition>
         </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.detail-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1120px;
  padding: 36px 28px 88px;
}

/* ============ 返回链接 ============ */
.back {
  align-items: center;
  color: var(--field-teal);
  display: inline-flex;
  font: 800 11px var(--field-mono);
  gap: 7px;
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.back:hover { color: var(--field-deep); transform: translateX(-2px); }
.back:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 计划页头 ============ */
.plan-header {
  border-bottom: 2px solid var(--field-ink);
  margin-top: 25px;
  padding-bottom: 25px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.plan-header > p, .section-label {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .11em;
  margin: 0;
}

.plan-header h1 {
  font-size: clamp(38px, 6vw, 67px);
  line-height: 1.04;
  margin: 12px 0 20px;
}

.summary { display: flex; flex-wrap: wrap; gap: 8px; }

.summary span {
  border: 1px solid var(--field-line);
  color: var(--field-ink-soft);
  font: 700 11px var(--field-mono);
  padding: 7px 9px;
}

/* ============ 通知条 ============ */
.notice {
  align-items: center;
  background: #e4f4ee;
  color: var(--field-teal);
  display: flex;
  font-size: 13px;
  gap: 8px;
  margin: 18px 0 0;
  padding: 10px 12px;
}

.notice.error { background: #fff0ee; color: var(--field-coral); }

/* ============ 布局栅格 ============ */
.detail-grid {
  align-items: start;
  display: grid;
  gap: 58px;
  grid-template-columns: minmax(0, 1fr) 270px;
  margin-top: 32px;
}

.reading-column { display: grid; gap: 31px; }

/* ============ 阅读列 ============ */
.intro { border-left: 3px solid var(--field-coral); padding-left: 18px; }
.intro > p:last-child { color: var(--field-ink-soft); font-size: 17px; line-height: 1.75; margin: 10px 0 0; }

.safety { background: var(--travel-sky); display: flex; gap: 11px; padding: 16px; }
.safety > svg { color: var(--field-coral); flex: 0 0 auto; }
.safety strong { font-size: 14px; }
.safety p, .action-panel p { color: var(--field-ink-soft); font-size: 13px; line-height: 1.6; margin: 6px 0 0; }

/* ============ 操作侧栏 ============ */
.action-rail { position: sticky; top: 94px; }

.action-panel {
  border-top: 2px solid var(--field-ink);
  display: grid;
  gap: 12px;
  padding-top: 16px;
}

.action-panel h2 { font-size: 20px; margin: 0; }

.action-panel textarea, .metadata-form input, .metadata-form select, .metadata-form textarea {
  border: 1px solid var(--field-line);
  color: var(--field-ink);
  font: inherit;
  min-height: 42px;
  outline-color: var(--field-teal);
  padding: 10px;
  transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.action-panel textarea:focus-visible, .metadata-form input:focus-visible, .metadata-form select:focus-visible, .metadata-form textarea:focus-visible {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.action-panel textarea, .metadata-form textarea { resize: vertical; }

.action-panel button, .application-actions button, .state-panel button {
  align-items: center;
  background: var(--field-ink);
  border: 1px solid var(--field-ink);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 7px;
  justify-content: center;
  min-height: 40px;
  padding: 9px 11px;
  transition: background-color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.action-panel button:hover:not(:disabled), .application-actions button:hover:not(:disabled), .state-panel button:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  transform: translateY(-1px);
  box-shadow: var(--shadow-soft);
}

.action-panel button:active:not(:disabled), .application-actions button:active:not(:disabled), .state-panel button:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.action-panel button:focus-visible, .application-actions button:focus-visible, .state-panel button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.action-panel button.secondary { background: #fff; color: var(--field-ink); }
.action-panel button.secondary:hover:not(:disabled) { background: var(--field-teal-soft); border-color: var(--field-teal); color: var(--field-teal); }

.action-panel button.quiet { background: transparent; border-color: var(--field-line); color: var(--field-ink-soft); }
.action-panel button.quiet:hover:not(:disabled) { background: var(--field-paper); border-color: var(--field-coral); color: var(--field-coral); }

button:disabled { cursor: not-allowed; opacity: .5; }

/* ============ 状态面板 ============ */
.state-panel {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: center;
  min-height: 270px;
}

/* ============ 成员 / 申请 ============ */
.section-heading {
  align-items: center;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 8px;
  padding-bottom: 9px;
}

.section-heading h2 { font-size: 17px; margin: 0; }

.members ul { display: grid; gap: 9px; list-style: none; margin: 14px 0 0; padding: 0; }
.members li { align-items: center; display: grid; gap: 8px; grid-template-columns: 30px 1fr auto; }

.avatar {
  align-items: center;
  background: var(--field-sand);
  border-radius: 50%;
  display: flex;
  font-size: 12px;
  height: 30px;
  justify-content: center;
}

.members small, .muted { color: var(--field-muted); font-size: 12px; }

.applications { display: grid; gap: 13px; }
.applications article { border-bottom: 1px solid var(--field-line); display: flex; gap: 16px; justify-content: space-between; padding-bottom: 13px; }
.applications article p { font-size: 13px; margin: 5px 0 0; }
.application-actions { display: flex; gap: 6px; }
.application-actions button { font-size: 11px; min-height: 32px; }

/* ============ 编辑表单 ============ */
.metadata-form { border-top: 1px solid var(--field-line); display: grid; gap: 10px; padding-top: 13px; }
.metadata-form > label, .metadata-form fieldset label { color: var(--field-ink-soft); display: grid; font-size: 12px; font-weight: 800; gap: 6px; }
.metadata-form small { color: var(--field-muted); font-size: 11px; font-weight: 500; }
.metadata-form fieldset { border: 0; border-bottom: 1px solid var(--field-line); border-top: 1px solid var(--field-line); display: flex; flex-wrap: wrap; gap: 7px; padding: 10px 0; }
.metadata-form legend { font-size: 12px; font-weight: 800; padding: 0 8px 0 0; }
.metadata-form fieldset label { align-items: center; display: flex; }
.metadata-form fieldset input { min-height: auto; padding: 0; }

.budget { display: grid; gap: 7px; grid-template-columns: 1fr 1fr 80px; }
.budget label { color: var(--field-ink-soft); display: grid; font-size: 11px; font-weight: 800; gap: 6px; }

/* ============ 群资料表单 ============ */
.group-profile .form-error { color: var(--field-coral); font-size: 12px; margin: 0; }
.group-profile-actions { display: flex; gap: 8px; }
.group-profile-actions button { flex: 1; }

/* ============ 响应式 ============ */
@media (max-width: 760px) {
  .detail-page { padding: 24px 18px 58px; }
  .detail-grid { gap: 34px; grid-template-columns: 1fr; }
  .action-rail { position: static; }
  .plan-header h1 { font-size: 38px; }
  .budget { grid-template-columns: 1fr 1fr; }
  .budget label:last-child { grid-column: span 2; }
  .applications article { align-items: start; flex-direction: column; }
}

@media (prefers-reduced-motion: reduce) {
  .plan-header { animation: none; }
  .back, .action-panel button, .application-actions button, .state-panel button,
  .action-panel textarea, .metadata-form input, .metadata-form select, .metadata-form textarea { transition: none; }
}
</style>
