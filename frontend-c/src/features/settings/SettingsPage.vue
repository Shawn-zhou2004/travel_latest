<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Check, ImagePlus, LoaderCircle, Save } from 'lucide-vue-next'
import { getPrivateImageUrl, uploadPrivateImage } from '@/features/media/api'
import { syncSettingsToAiMemory } from '@/features/ai/assistantApi'
import { getMyProfile, updateMyProfile, type Profile } from '@/features/profile/api'
import {
  getMySettings,
  interestTags,
  updateMySettings,
  type BudgetLevel,
  type InterestTag,
  type ProfileVisibility,
  type TravelPace,
  type TravelerType,
  type UserSettings,
} from './api'
import { useReveal } from '@/composables/useReveal'
import { useAuthStore } from '@/stores/auth'

const root = ref<HTMLElement | null>(null)
const auth = useAuthStore()
useReveal(root)

type SectionKey = 'profile' | 'travel' | 'notifications' | 'privacy'
type SectionState = Record<SectionKey, { saving: boolean; error: string; success: string }>

const profile = ref<Profile | null>(null)
const settings = ref<UserSettings | null>(null)
const avatarUrl = ref('')
const loading = ref(true)
const loadError = ref('')
const uploading = ref(false)
const syncingAiMemory = ref(false)
const aiMemorySyncError = ref('')
const aiMemorySyncSuccess = ref('')
const states = reactive<SectionState>({
  profile: { saving: false, error: '', success: '' },
  travel: { saving: false, error: '', success: '' },
  notifications: { saving: false, error: '', success: '' },
  privacy: { saving: false, error: '', success: '' },
})

const profileDraft = reactive({ nickname: '', avatar_asset_id: null as string | null })
const travelDraft = reactive({
  departure_city: '',
  budget_level: 'balanced' as BudgetLevel,
  travel_pace: 'balanced' as TravelPace,
  interest_tags: [] as InterestTag[],
  traveler_type: 'friends' as TravelerType,
})
const notificationDraft = reactive({
  notifications_enabled: true,
  order_notifications: true,
  itinerary_notifications: true,
  community_notifications: true,
})
const privacyDraft = reactive({ profile_visibility: 'collaborators' as ProfileVisibility })
const snapshots = reactive<Record<SectionKey, string>>({ profile: '', travel: '', notifications: '', privacy: '' })
const budgetChoices: { value: BudgetLevel; label: string }[] = [{ value: 'economy', label: '经济' }, { value: 'balanced', label: '均衡' }, { value: 'premium', label: '舒适' }]
const paceChoices: { value: TravelPace; label: string }[] = [{ value: 'relaxed', label: '悠闲' }, { value: 'balanced', label: '适中' }, { value: 'packed', label: '充实' }]
const travelerChoices: { value: TravelerType; label: string }[] = [{ value: 'solo', label: '独自出行' }, { value: 'couple', label: '情侣' }, { value: 'friends', label: '朋友' }, { value: 'family', label: '家庭' }]
const notificationChoices = [
  { key: 'order_notifications', title: '订单动态', text: '支付、出票和售后进度。' },
  { key: 'itinerary_notifications', title: '行程更新', text: '规划任务和行程变更。' },
  { key: 'community_notifications', title: '同行互动', text: '同行计划和社区消息。' },
] as const

function snapshot(value: object) { return JSON.stringify(value) }
function message(reason: unknown, fallback: string) { return reason instanceof Error ? reason.message : fallback }
function resetState(section: SectionKey) { states[section].error = ''; states[section].success = '' }

function copyProfile(value: Profile) {
  profile.value = value
  profileDraft.nickname = value.nickname ?? ''
  profileDraft.avatar_asset_id = value.avatar_asset_id
  snapshots.profile = snapshot(profileDraft)
}

function copySettings(value: UserSettings) {
  settings.value = value
  travelDraft.departure_city = value.departure_city ?? ''
  travelDraft.budget_level = value.budget_level
  travelDraft.travel_pace = value.travel_pace
  travelDraft.interest_tags = [...value.interest_tags]
  travelDraft.traveler_type = value.traveler_type
  notificationDraft.notifications_enabled = value.notifications_enabled
  notificationDraft.order_notifications = value.order_notifications
  notificationDraft.itinerary_notifications = value.itinerary_notifications
  notificationDraft.community_notifications = value.community_notifications
  privacyDraft.profile_visibility = value.profile_visibility
  snapshots.travel = snapshot(travelDraft)
  snapshots.notifications = snapshot(notificationDraft)
  snapshots.privacy = snapshot(privacyDraft)
}

async function loadAvatar() {
  avatarUrl.value = ''
  if (!profile.value?.avatar_asset_id) return
  try { avatarUrl.value = await getPrivateImageUrl(profile.value.avatar_asset_id) } catch { /* Keep the initial fallback when private URL resolution fails. */ }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [loadedProfile, loadedSettings] = await Promise.all([getMyProfile(), getMySettings()])
    copyProfile(loadedProfile)
    copySettings(loadedSettings)
    await loadAvatar()
  } catch (reason) { loadError.value = message(reason, '设置暂时无法加载。') }
  finally { loading.value = false }
}

const profileDirty = computed(() => snapshot(profileDraft) !== snapshots.profile)
const travelDirty = computed(() => snapshot(travelDraft) !== snapshots.travel)
const notificationsDirty = computed(() => snapshot(notificationDraft) !== snapshots.notifications)
const privacyDirty = computed(() => snapshot(privacyDraft) !== snapshots.privacy)
const dirty = computed(() => profileDirty.value || travelDirty.value || notificationsDirty.value || privacyDirty.value)

async function saveProfile() {
  resetState('profile')
  states.profile.saving = true
  try {
    const updated = await updateMyProfile({ nickname: profileDraft.nickname.trim() || null, avatar_asset_id: profileDraft.avatar_asset_id })
    copyProfile(updated)
    auth.updateUserProfile({ nickname: updated.nickname, avatar_asset_id: updated.avatar_asset_id })
    await loadAvatar()
    states.profile.success = '账户资料已保存。'
  } catch (reason) { states.profile.error = message(reason, '账户资料保存失败。') }
  finally { states.profile.saving = false }
}

async function uploadAvatar(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || uploading.value) return
  resetState('profile')
  uploading.value = true
  try {
    profileDraft.avatar_asset_id = await uploadPrivateImage(file, 'avatar')
    states.profile.success = '头像已上传，保存账户资料以应用更改。'
  } catch (reason) { states.profile.error = message(reason, '头像上传失败。') }
  finally { uploading.value = false; (event.target as HTMLInputElement).value = '' }
}

async function saveTravel() {
  resetState('travel')
  states.travel.saving = true
  try {
    copySettings(await updateMySettings({ ...travelDraft, departure_city: travelDraft.departure_city.trim() || null, interest_tags: [...travelDraft.interest_tags] }))
    states.travel.success = '旅行偏好已保存。'
  } catch (reason) { states.travel.error = message(reason, '旅行偏好保存失败。') }
  finally { states.travel.saving = false }
}

async function syncAiMemory() {
  if (syncingAiMemory.value || travelDirty.value || states.travel.saving) return
  syncingAiMemory.value = true
  aiMemorySyncError.value = ''
  aiMemorySyncSuccess.value = ''
  try {
    await syncSettingsToAiMemory()
    aiMemorySyncSuccess.value = '当前设置已更新到 AI 旅行档案。'
  } catch (reason) { aiMemorySyncError.value = message(reason, '同步 AI 旅行档案失败。') }
  finally { syncingAiMemory.value = false }
}

async function saveNotifications() {
  resetState('notifications')
  states.notifications.saving = true
  try {
    copySettings(await updateMySettings({ ...notificationDraft }))
    states.notifications.success = '通知偏好已保存。'
  } catch (reason) { states.notifications.error = message(reason, '通知偏好保存失败。') }
  finally { states.notifications.saving = false }
}

async function savePrivacy() {
  resetState('privacy')
  states.privacy.saving = true
  try {
    copySettings(await updateMySettings({ ...privacyDraft }))
    states.privacy.success = '隐私设置已保存。'
  } catch (reason) { states.privacy.error = message(reason, '隐私设置保存失败。') }
  finally { states.privacy.saving = false }
}

function toggleTag(tag: InterestTag) {
  travelDraft.interest_tags = travelDraft.interest_tags.includes(tag)
    ? travelDraft.interest_tags.filter((value) => value !== tag)
    : [...travelDraft.interest_tags, tag]
}

function confirmBeforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => { window.addEventListener('beforeunload', confirmBeforeUnload); void load() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', confirmBeforeUnload))
onBeforeRouteLeave(() => !dirty.value || window.confirm('有未保存的设置，确定离开吗？'))
</script>

<template>
  <main class="settings-page" aria-labelledby="settings-title" ref="root">
    <header class="settings-heading" data-reveal><p class="eyebrow">ACCOUNT / SETTINGS</p><h1 id="settings-title">个人设置</h1><p>管理账户资料、出行习惯和与同行者共享的信息。</p></header>
    <div v-if="loading" class="loading-stack" role="status" aria-label="正在加载设置"><span /><span /><span /><span /></div>
    <p v-else-if="loadError" class="load-error" role="alert">{{ loadError }}</p>
    <div v-else class="settings-layout">
      <nav class="section-index" aria-label="设置分区"><a href="#profile">账户资料</a><a href="#travel">旅行偏好</a><a href="#notifications">通知</a><a href="#privacy">隐私</a></nav>
      <div class="settings-sections">
        <section id="profile" data-testid="settings-profile" class="settings-section" aria-labelledby="profile-title">
          <header><p class="section-number">01</p><div><h2 id="profile-title">账户资料</h2><p>修改你的显示名称和旅行头像。</p></div></header>
          <div class="avatar-row"><div class="avatar" aria-hidden="true"><img v-if="avatarUrl" :src="avatarUrl" alt=""><span v-else>{{ (profileDraft.nickname || '旅').slice(0, 1).toUpperCase() }}</span></div><div><label class="upload-button"><ImagePlus :size="16" />{{ uploading ? '正在上传' : '更换头像' }}<input type="file" accept="image/jpeg,image/png,image/webp" :disabled="uploading || states.profile.saving" @change="uploadAvatar"></label><p class="field-note">支持 JPEG、PNG 和 WebP 格式。</p></div></div>
          <label class="field">显示名称<input v-model="profileDraft.nickname" name="nickname" maxlength="64" autocomplete="nickname" placeholder="填写显示名称" :disabled="states.profile.saving"></label>
          <div class="section-footer"><div><p v-if="states.profile.error" role="alert" class="message error">{{ states.profile.error }}</p><p v-if="states.profile.success" role="status" class="message success"><Check :size="15" />{{ states.profile.success }}</p></div><button data-testid="save-profile" type="button" class="save-button" :disabled="states.profile.saving || uploading || !profileDirty" @click="saveProfile"><Save :size="16" />{{ states.profile.saving ? '正在保存' : '保存资料' }}</button></div>
        </section>

        <section id="travel" data-testid="settings-travel" class="settings-section" aria-labelledby="travel-title">
          <header><p class="section-number">02</p><div><h2 id="travel-title">旅行偏好</h2><p>这些选择会作为新行程的默认参考。</p></div></header>
          <div class="field-grid"><label class="field">常用出发城市<input v-model="travelDraft.departure_city" name="departure-city" maxlength="128" placeholder="例如：杭州" :disabled="states.travel.saving"></label></div>
          <fieldset :disabled="states.travel.saving"><legend>预算倾向</legend><div class="choice-row"><label v-for="choice in budgetChoices" :key="choice.value" class="choice"><input v-model="travelDraft.budget_level" type="radio" name="budget-level" :value="choice.value">{{ choice.label }}</label></div></fieldset>
          <fieldset :disabled="states.travel.saving"><legend>行程节奏</legend><div class="choice-row"><label v-for="choice in paceChoices" :key="choice.value" class="choice"><input v-model="travelDraft.travel_pace" type="radio" name="travel-pace" :value="choice.value">{{ choice.label }}</label></div></fieldset>
           <fieldset :disabled="states.travel.saving"><legend>同行方式</legend><div class="choice-row"><label v-for="choice in travelerChoices" :key="choice.value" class="choice"><input v-model="travelDraft.traveler_type" type="radio" name="traveler-type" :value="choice.value">{{ choice.label }}</label></div></fieldset>
           <fieldset :disabled="states.travel.saving"><legend>感兴趣的体验</legend><div class="tag-grid"><button v-for="tag in interestTags" :key="tag.value" type="button" class="tag-button" :class="{ selected: travelDraft.interest_tags.includes(tag.value) }" :aria-pressed="travelDraft.interest_tags.includes(tag.value)" @click="toggleTag(tag.value)">{{ tag.label }}</button></div></fieldset>
           <div class="ai-memory-sync"><div><strong>AI 旅行档案</strong><p>同步后可在旅行助手的“我的记忆”中查看、编辑或删除。</p><p v-if="travelDirty" class="message error">请先保存旅行偏好，再同步为 AI 记忆。</p><p v-if="aiMemorySyncError" role="alert" class="message error">{{ aiMemorySyncError }}</p><p v-if="aiMemorySyncSuccess" role="status" class="message success"><Check :size="15" />{{ aiMemorySyncSuccess }}</p></div><button data-testid="sync-ai-memory" type="button" class="save-button" :disabled="syncingAiMemory || travelDirty || states.travel.saving" @click="syncAiMemory"><LoaderCircle v-if="syncingAiMemory" :size="16" class="spinning" /><Save v-else :size="16" />{{ syncingAiMemory ? '正在同步' : '同步为 AI 记忆' }}</button></div>
           <div class="section-footer"><div><p v-if="states.travel.error" role="alert" class="message error">{{ states.travel.error }}</p><p v-if="states.travel.success" role="status" class="message success"><Check :size="15" />{{ states.travel.success }}</p></div><button data-testid="save-travel" type="button" class="save-button" :disabled="states.travel.saving || !travelDirty" @click="saveTravel"><Save :size="16" />{{ states.travel.saving ? '正在保存' : '保存偏好' }}</button></div>
        </section>

        <section id="notifications" data-testid="settings-notifications" class="settings-section" aria-labelledby="notifications-title">
          <header><p class="section-number">03</p><div><h2 id="notifications-title">通知</h2><p>选择希望收到的旅行动态。</p></div></header>
          <label class="switch-row master"><span><strong>接收通知</strong><small>关闭后将停止所有类别通知。</small></span><input v-model="notificationDraft.notifications_enabled" type="checkbox" role="switch" :disabled="states.notifications.saving"></label>
          <div class="switch-list" :class="{ muted: !notificationDraft.notifications_enabled }"><label v-for="item in notificationChoices" :key="item.key" class="switch-row"><span><strong>{{ item.title }}</strong><small>{{ item.text }}</small></span><input v-model="notificationDraft[item.key]" type="checkbox" role="switch" :disabled="states.notifications.saving || !notificationDraft.notifications_enabled"></label></div>
          <div class="section-footer"><div><p v-if="states.notifications.error" role="alert" class="message error">{{ states.notifications.error }}</p><p v-if="states.notifications.success" role="status" class="message success"><Check :size="15" />{{ states.notifications.success }}</p></div><button type="button" class="save-button" :disabled="states.notifications.saving || !notificationsDirty" @click="saveNotifications"><Save :size="16" />{{ states.notifications.saving ? '正在保存' : '保存通知' }}</button></div>
        </section>

        <section id="privacy" data-testid="settings-privacy" class="settings-section" aria-labelledby="privacy-title">
          <header><p class="section-number">04</p><div><h2 id="privacy-title">隐私</h2><p>控制同行计划中向其他成员展示的资料。</p></div></header>
          <fieldset :disabled="states.privacy.saving"><legend>个人资料可见范围</legend><div class="privacy-options"><label class="privacy-option"><input v-model="privacyDraft.profile_visibility" type="radio" name="profile-visibility" value="collaborators"><span><strong>向同行者显示</strong><small>已加入同一同行计划的成员可查看你的名称和头像。</small></span></label><label class="privacy-option"><input v-model="privacyDraft.profile_visibility" type="radio" name="profile-visibility" value="private"><span><strong>仅自己可见</strong><small>其他同行成员不会看到你的名称和头像。</small></span></label></div></fieldset>
          <div class="section-footer"><div><Transition name="fade"><p v-if="states.privacy.error" role="alert" class="message error">{{ states.privacy.error }}</p></Transition><Transition name="fade"><p v-if="states.privacy.success" role="status" class="message success"><Check :size="15" />{{ states.privacy.success }}</p></Transition></div><button data-testid="save-privacy" type="button" class="save-button" :disabled="states.privacy.saving || !privacyDirty" @click="savePrivacy"><Save :size="16" />{{ states.privacy.saving ? '正在保存' : '保存隐私' }}</button></div>
        </section>
      </div>
    </div>
  </main>
</template>

<style scoped>
.settings-page { color: var(--field-ink); margin: 0 auto; max-width: 1160px; padding: 52px 28px 84px; }.settings-heading { animation: header-enter var(--motion-slow) var(--ease-out) both; border-bottom: 2px solid var(--field-ink); padding: 0 0 24px 18px; position: relative; }.settings-heading::before { background: var(--field-saffron); content: ''; height: 100%; left: 0; position: absolute; top: 0; width: 4px; }.eyebrow, .section-number { color: var(--field-teal); font: 800 11px var(--field-mono); letter-spacing: .08em; margin: 0 0 9px; }.settings-heading h1 { font-size: 38px; line-height: 1.1; margin: 0; }.settings-heading p:last-child { color: var(--field-ink-soft); margin: 11px 0 0; }.settings-layout { animation: content-enter var(--motion-slow) var(--ease-out) both; display: grid; gap: 56px; grid-template-columns: 150px minmax(0, 1fr); padding-top: 38px; }.section-index { align-self: start; display: grid; gap: 5px; position: sticky; top: 98px; }.section-index a { border-left: 2px solid var(--field-line); color: var(--field-muted); font-size: 13px; padding: 8px 0 8px 12px; text-decoration: none; }.section-index a:hover, .section-index a:focus-visible { border-color: var(--field-saffron); color: var(--field-teal); outline: 0; }.settings-sections { display: grid; gap: 48px; }.settings-section { border-top: 1px solid var(--field-line); padding-top: 23px; scroll-margin-top: 92px; }.settings-section > header { display: grid; gap: 14px; grid-template-columns: 32px minmax(0, 1fr); margin-bottom: 27px; }.section-number { margin: 4px 0 0; }.settings-section h2 { font-size: 23px; line-height: 1.2; margin: 0; }.settings-section header p:last-child { color: var(--field-muted); font-size: 14px; margin: 7px 0 0; }.avatar-row { align-items: center; display: flex; gap: 18px; margin-bottom: 22px; }.avatar { align-items: center; background: var(--field-teal-soft); border: 3px solid var(--field-white); box-shadow: 0 0 0 1px var(--field-line); color: var(--field-teal); display: flex; font-size: 29px; font-weight: 800; height: 82px; justify-content: center; overflow: hidden; width: 82px; }.avatar img { height: 100%; object-fit: cover; width: 100%; }.upload-button, .save-button { align-items: center; border: 1px solid var(--field-deep); border-radius: 6px; cursor: pointer; display: inline-flex; font-size: 13px; font-weight: 800; gap: 8px; min-height: 42px; padding: 0 14px; }.upload-button { background: var(--field-white); color: var(--field-deep); transition: background-color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }.upload-button input { height: 1px; opacity: 0; position: absolute; width: 1px; }.field-note, small { color: var(--field-muted); display: block; font-size: 12px; line-height: 1.5; margin: 7px 0 0; }.field, fieldset { border: 0; display: grid; font-size: 13px; font-weight: 800; gap: 8px; margin: 0 0 21px; padding: 0; }.field input { background: var(--field-white); border: 1px solid var(--field-line); border-radius: 5px; color: var(--field-ink); font: inherit; font-weight: 500; min-height: 46px; padding: 0 12px; }.field input:focus-visible, .choice:has(input:focus-visible), .privacy-option:has(input:focus-visible), .tag-button:focus-visible, .switch-row:has(input:focus-visible) { outline: 3px solid var(--field-teal-soft); outline-offset: 2px; }.choice-row { display: flex; flex-wrap: wrap; gap: 8px; }.choice { align-items: center; border: 1px solid var(--field-line); border-radius: 5px; cursor: pointer; display: inline-flex; font-weight: 700; gap: 7px; min-height: 38px; padding: 0 11px; }.choice:has(input:checked) { background: var(--field-teal-soft); border-color: var(--field-teal); color: var(--field-teal); }.choice input { accent-color: var(--field-teal); }.tag-grid { display: flex; flex-wrap: wrap; gap: 8px; }.tag-button { background: var(--field-white); border: 1px solid var(--field-line); border-radius: 5px; color: var(--field-ink-soft); cursor: pointer; font: 700 13px inherit; min-height: 36px; padding: 0 11px; }.tag-button.selected { background: var(--field-teal); border-color: var(--field-teal); color: var(--field-white); }.switch-list { border-top: 1px solid var(--field-line); }.switch-row { align-items: center; border-bottom: 1px solid var(--field-line); cursor: pointer; display: flex; justify-content: space-between; min-height: 74px; padding: 13px 0; }.switch-row strong { font-size: 14px; }.switch-row input { accent-color: var(--field-teal); height: 20px; width: 36px; }.switch-list.muted { opacity: .52; }.privacy-options { display: grid; gap: 10px; }.privacy-option { align-items: flex-start; border: 1px solid var(--field-line); border-radius: 6px; cursor: pointer; display: flex; gap: 11px; padding: 15px; }.privacy-option:has(input:checked) { background: var(--field-teal-soft); border-color: var(--field-teal); }.privacy-option input { accent-color: var(--field-teal); margin-top: 3px; }.section-footer { align-items: center; display: flex; gap: 16px; justify-content: space-between; margin-top: 27px; min-height: 42px; }.save-button { background: var(--field-deep); color: var(--field-white); }.save-button:disabled, .upload-button:has(input:disabled) { cursor: wait; opacity: .55; }.message { align-items: center; display: flex; font-size: 13px; gap: 6px; margin: 0; }.error, .load-error { color: #9b3429; }.success { color: #315f35; }.loading-stack { display: grid; gap: 15px; padding-top: 38px; }.loading-stack span { background: linear-gradient(90deg, var(--field-teal-soft), var(--field-white), var(--field-teal-soft)); height: 84px; }.load-error { padding-top: 38px; } @media (max-width: 767px) { .settings-page { padding: 34px 18px 60px; }.settings-heading h1 { font-size: 31px; }.settings-layout { display: block; padding-top: 30px; }.section-index { display: flex; margin-bottom: 32px; overflow-x: auto; position: static; }.section-index a { border-bottom: 2px solid var(--field-line); border-left: 0; padding: 7px 11px; white-space: nowrap; }.settings-sections { gap: 38px; }.section-footer { align-items: flex-start; flex-direction: column; }.save-button { justify-content: center; width: 100%; } } /* ============ 交互态 ============ */
.save-button:not(:disabled):hover { background: var(--field-teal); border-color: var(--field-teal); transform: translateY(-1px); box-shadow: var(--shadow-soft); }
.save-button:not(:disabled):active { transform: translateY(0) scale(0.98); }
.save-button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.ai-memory-sync { align-items: start; border-top: 1px solid var(--field-line); display: flex; gap: 18px; justify-content: space-between; margin-top: 24px; padding-top: 20px; }.ai-memory-sync strong { display: block; font-size: 14px; }.ai-memory-sync p { color: var(--field-muted); font-size: 13px; margin: 5px 0 0; }.ai-memory-sync .message { margin-top: 9px; }

.upload-button:not(:has(input:disabled)):hover { background: var(--field-teal-soft); border-color: var(--field-teal); transform: translateY(-1px); }
.upload-button:not(:has(input:disabled)):active { transform: translateY(0) scale(0.98); }
.upload-button:focus-within { outline: 3px solid var(--field-saffron); outline-offset: 2px; }

.tag-button:hover { border-color: var(--field-teal); color: var(--field-teal); transform: translateY(-1px); }
.tag-button:active { transform: translateY(0) scale(0.97); }
.tag-button.selected:hover { background: var(--field-deep); border-color: var(--field-deep); color: #fff; }

.choice:hover { border-color: var(--field-teal); }
.privacy-option:hover { border-color: var(--field-teal); }

@keyframes header-enter { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes content-enter { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

@media (prefers-reduced-motion: reduce) {
  * { scroll-behavior: auto; }
  .settings-heading, .settings-layout { animation: none; }
  .save-button, .upload-button, .tag-button { transition: none; }
  .save-button:not(:disabled):hover, .upload-button:not(:has(input:disabled)):hover, .tag-button:hover { transform: none; }
}
</style>
