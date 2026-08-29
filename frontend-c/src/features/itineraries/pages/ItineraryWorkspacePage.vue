<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowLeft, CalendarPlus, Check, CircleAlert, Download, FileDown, Link, LockKeyhole, MapPinned, MessageCircle, MoreHorizontal, Plus, RefreshCw, Save, Search, Send, Share2, Trash2, UserPlus, Users, X } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { useItineraryStore } from '../stores/itinerary'
import { useItineraryExportStore } from '../stores/export'
import { acceptCollaborator, createShareToken, deleteItinerary, getCompanionWorkspace, getItinerary, inviteCollaborator, listItineraryVersions, removeItineraryDay, searchPOIs, type CompanionWorkspaceSummary, type ItineraryEvent, type ItineraryVersion, type POIRecord } from '../api'
import { normalizeApiError } from '@/services/api'
import { newClientId } from '@/services/id'
import { closeCompanionPlan, completeCompanionPlan } from '@/features/community/companionPlansApi'
import Timeline from '../components/Timeline.vue'
import MapPanel from '../components/MapPanel.vue'
import TripSupportPanel from '../components/TripSupportPanel.vue'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ itineraryId: string }>()
const store = useItineraryStore()
const exportStore = useItineraryExportStore()
const route = useRoute()
const router = useRouter()
const activeDay = ref(0)
const selectedEventId = ref('')
const notesDraft = ref('')
const actionError = ref('')
const busyEventId = ref('')
const addingDay = ref(false)
const newDayDate = ref('')
const savingNotes = ref(false)
const poiQuery = ref('')
const poiResults = ref<POIRecord[]>([])
const searchingPOIs = ref(false)
const addingPOIId = ref('')
const sharing = ref(false)
const shareUrl = ref('')
const shareError = ref('')
const creatingShare = ref(false)
const inviteUserId = ref('')
const inviteRole = ref<'viewer' | 'editor'>('editor')
const inviteUrl = ref('')
const inviting = ref(false)
const exporting = ref(false)
const exportVersions = ref<ItineraryVersion[]>([])
const selectedExportVersion = ref<number | null>(null)
const loadingVersions = ref(false)
const inaccessible = ref(false)
const itineraryDetail = ref<Awaited<ReturnType<typeof getItinerary>> | null>(null)
const companionWorkspace = ref<CompanionWorkspaceSummary | null>(null)
const companionLoading = ref(false)
const companionBusy = ref(false)
const removeDayId = ref('')
const deletingDay = ref(false)
const deletingItinerary = ref(false)
const deleteItineraryOpen = ref(false)
const deletionError = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)

const day = computed(() => store.snapshot?.days[activeDay.value])
const selectedEvent = computed<ItineraryEvent | undefined>(() => day.value?.events.find((event) => event.id === selectedEventId.value))
const hasDays = computed(() => Boolean(store.snapshot?.days.length))
const dayLabel = computed(() =>
  day.value
    ? new Date(`${day.value.day_date}T00:00:00`).toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
      })
    : '未安排日期',
)
const dayPendingRemoval = computed(() => store.snapshot?.days.find((item) => item.id === removeDayId.value))

function dateValue(value: Date) {
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

watch(
  selectedEvent,
  (event) => {
  notesDraft.value = event?.notes ?? ''
  },
  { immediate: true },
)

onMounted(async () => {
  exportStore.reset()
  store.itineraryId = props.itineraryId
  try {
    const itinerary = await getItinerary(props.itineraryId)
    itineraryDetail.value = itinerary
    store.setSnapshot(itinerary.snapshot, itinerary.version)
    store.accessRole = itinerary.access_role
    await loadCompanionWorkspace()
    const inviteId = typeof route.query.invite === 'string' ? route.query.invite : ''
    if (inviteId) {
      await acceptCollaborator(props.itineraryId, inviteId)
      const accepted = await getItinerary(props.itineraryId)
      itineraryDetail.value = accepted
      store.setSnapshot(accepted.snapshot, accepted.version)
      store.accessRole = accepted.access_role
      await loadCompanionWorkspace()
    }
  } catch {
    inaccessible.value = true
    store.state = 'unavailable'
  }
})

onBeforeUnmount(() => exportStore.reset())

function selectEvent(eventId: string) {
  selectedEventId.value = eventId
  actionError.value = ''
}

async function loadCompanionWorkspace() {
  companionLoading.value = true
  try {
    companionWorkspace.value = await getCompanionWorkspace(props.itineraryId)
  } catch {
    companionWorkspace.value = null
  } finally {
    companionLoading.value = false
  }
}

async function transitionCompanion(action: 'close' | 'complete') {
  const companion = companionWorkspace.value
  if (!companion || companion.role !== 'owner' || companion.review_status !== 'approved' || companionBusy.value) return
  companionBusy.value = true
  actionError.value = ''
  try {
    await (action === 'close' ? closeCompanionPlan(companion.id) : completeCompanionPlan(companion.id))
    await loadCompanionWorkspace()
  } catch (reason) {
    actionError.value = reason instanceof Error ? reason.message : '同行计划状态暂未更新。'
  } finally {
    companionBusy.value = false
  }
}

async function addDay() {
  const snapshot = store.snapshot
  if (!snapshot || addingDay.value) return
  const sourceDate = snapshot.days.at(-1)?.day_date ?? snapshot.end_date
  const nextDate = new Date(`${sourceDate}T00:00:00`)
  nextDate.setDate(nextDate.getDate() + 1)
  const nextDateValue = newDayDate.value || dateValue(nextDate)
  addingDay.value = true
  actionError.value = ''
  const result = await store.apply('add_day', { day_date: nextDateValue })
  if (result?.code !== 'APPLIED') actionError.value = result?.code === 'VERSION_CONFLICT' ? '计划已在别处更新，请刷新后继续。' : '这一天暂时没有加入，请稍后重试。'
  else activeDay.value = Math.max(0, (store.snapshot?.days.length ?? 1) - 1)
  if (result?.code === 'APPLIED') newDayDate.value = ''
  addingDay.value = false
}

async function moveEvent(eventId: string, direction: 'up' | 'down') {
  busyEventId.value = eventId
  actionError.value = ''
  const result = await store.apply('reorder_event', {
    event_id: eventId,
    direction,
  })
  if (result?.code !== 'APPLIED') actionError.value = '地点顺序没有保存。'
  busyEventId.value = ''
}

async function removeEvent(eventId: string) {
  busyEventId.value = eventId
  actionError.value = ''
  const result = await store.apply('remove_event', { event_id: eventId })
  if (result?.code === 'APPLIED' && selectedEventId.value === eventId) selectedEventId.value = ''
  else if (result?.code !== 'APPLIED') actionError.value = '地点没有移出计划。'
  busyEventId.value = ''
}

function openDayRemoval(dayId: string) {
  removeDayId.value = dayId
  deletionError.value = ''
}

function closeDayRemoval() {
  if (!deletingDay.value) removeDayId.value = ''
}

async function confirmDayRemoval() {
  const dayId = removeDayId.value
  const days = store.snapshot?.days ?? []
  const removedIndex = days.findIndex((item) => item.id === dayId)
  if (!dayId || removedIndex < 0 || deletingDay.value) return
  deletingDay.value = true
  deletionError.value = ''
  try {
    const result = await removeItineraryDay(props.itineraryId, store.version, newClientId(), dayId)
    if (result.code === 'APPLIED' && result.snapshot && result.current_version !== null) {
      store.setSnapshot(result.snapshot, result.current_version)
      activeDay.value = result.snapshot.days.length ? Math.max(0, removedIndex - 1) : 0
      selectedEventId.value = ''
      removeDayId.value = ''
    } else if (result.code === 'VERSION_CONFLICT') {
      if (result.snapshot && result.current_version !== null) store.setSnapshot(result.snapshot, result.current_version)
      store.state = 'conflict'
      removeDayId.value = ''
    } else {
      deletionError.value = result.code === 'NOT_FOUND' ? '这一天已被移除，请刷新计划。' : '这一天暂时无法删除。'
    }
  } catch (reason) {
    deletionError.value = normalizeApiError(reason).message
  } finally {
    deletingDay.value = false
  }
}

function openItineraryDeletion() {
  deleteItineraryOpen.value = true
  deletionError.value = ''
}

function closeItineraryDeletion() {
  if (deletingItinerary.value) return
  deleteItineraryOpen.value = false
  deletionError.value = ''
}

async function confirmItineraryDeletion() {
  if (deletingItinerary.value) return
  deletingItinerary.value = true
  deletionError.value = ''
  try {
    await deleteItinerary(props.itineraryId)
    await router.push('/itineraries')
  } catch (reason) {
    const apiError = normalizeApiError(reason)
    deletionError.value = apiError.code === 'COMPANION_PLAN_ACTIVE' ? '请先结束或取消同行计划后再删除行程。' : apiError.message
  } finally {
    deletingItinerary.value = false
  }
}

async function saveNotes() {
  if (!selectedEvent.value || savingNotes.value) return
  savingNotes.value = true
  actionError.value = ''
  const result = await store.apply('update_event', {
    event_id: selectedEvent.value.id,
    notes: notesDraft.value.trim() || null,
  })
  if (result?.code !== 'APPLIED') actionError.value = '备注没有保存。'
  savingNotes.value = false
}

async function refreshRoute() {
  await store.recalculateRoute(day.value?.id ?? '')
}

async function searchPlaces() {
  if (!poiQuery.value.trim() || searchingPOIs.value) return
  searchingPOIs.value = true
  actionError.value = ''
  try {
    poiResults.value = await searchPOIs(poiQuery.value.trim())
    if (!poiResults.value.length) actionError.value = '没有找到可验证地点，请换一个更具体的名称。'
  } catch (reason) {
    actionError.value = reason instanceof Error ? reason.message : '地点搜索暂时不可用。'
  } finally {
    searchingPOIs.value = false
  }
}

async function addPlace(poi: POIRecord) {
  if (!day.value || addingPOIId.value) return
  addingPOIId.value = poi.id
  actionError.value = ''
  const result = await store.apply('add_event', {
    day_id: day.value.id,
    poi_id: poi.id,
  })
  if (result?.code === 'APPLIED') {
    selectedEventId.value = store.snapshot?.days[activeDay.value]?.events.at(-1)?.id ?? ''
    poiResults.value = []
    poiQuery.value = ''
  } else if (result?.code === 'MAP_UNAVAILABLE') {
    actionError.value = '这个地点暂时无法通过高德验证，请稍后重试。'
  } else {
    actionError.value = '地点没有加入当天计划。'
  }
  addingPOIId.value = ''
}

function reloadWorkspace() {
  window.location.reload()
}

async function createShareLink() {
  if (creatingShare.value) return
  creatingShare.value = true
  shareError.value = ''
  try {
    const share = await createShareToken(props.itineraryId)
    shareUrl.value = new URL(share.share_url, window.location.origin).toString()
  } catch {
    shareError.value = '无法创建分享链接，请稍后重试。'
  } finally {
    creatingShare.value = false
  }
}

async function createInvitation() {
  if (inviting.value || !inviteUserId.value.trim()) return
  inviting.value = true
  shareError.value = ''
  try {
    const collaborator = await inviteCollaborator(props.itineraryId, inviteUserId.value.trim(), inviteRole.value)
    const invitation = new URL(`/itineraries/${props.itineraryId}`, window.location.origin)
    invitation.searchParams.set('invite', collaborator.id)
    inviteUrl.value = invitation.toString()
  } catch {
    shareError.value = '邀请未创建。请确认用户 ID 正确且该用户已注册。'
  } finally {
    inviting.value = false
  }
}

async function copy(value: string) {
  if (!value) return
  await navigator.clipboard.writeText(value)
}

function closeExport() {
  exporting.value = false
  exportStore.reset()
}

async function openExport() {
  if (loadingVersions.value) return
  loadingVersions.value = true
  actionError.value = ''
  try {
    exportVersions.value = await listItineraryVersions(props.itineraryId)
    selectedExportVersion.value = exportVersions.value.some((version) => version.version_no === store.version) ? store.version : (exportVersions.value[0]?.version_no ?? null)
    exporting.value = true
  } catch {
    actionError.value = '历史版本暂时无法读取，不能创建导出。'
  } finally {
    loadingVersions.value = false
  }
}

function createExport() {
  if (selectedExportVersion.value !== null) void exportStore.create(props.itineraryId, selectedExportVersion.value)
}
</script>

<template><main ref="root" class="workspace"><section v-if="inaccessible" class="access-panel" role="alert"><LockKeyhole :size="28" /><p class="workspace-label">PRIVATE ITINERARY</p><h1>这份行程暂时不可访问。</h1><p>它可能已被删除、尚未向你的账户共享，或服务暂时不可用。</p><RouterLink class="primary-action" to="/itineraries"><ArrowLeft :size="16" />返回我的计划</RouterLink></section><template v-else><header class="workspace-header" data-reveal><div class="header-left"><RouterLink class="back-link" to="/itineraries"><ArrowLeft :size="16" />我的计划</RouterLink><div class="title-block"><p class="workspace-label"> ITINERARY / VERSION {{ store.version.toString().padStart(2, '0') }} </p><h1>{{ store.snapshot?.title || '你的路线' }}</h1><RouterLink v-if="itineraryDetail?.source_post_id" class="source-link" :to="`/community/${itineraryDetail.source_post_id}`">复制自田野笔记</RouterLink></div></div><div class="header-actions"><span class="save-indicator" :class="store.state"><Check :size="14" />{{ store.canEdit ? (store.state === 'saved' ? '已保存' : store.state === 'conflict' ? '需要刷新' : store.state === 'loading' ? '正在读取' : '未完成') : '只读查看' }}</span ><RouterLink v-if="store.canEdit" class="publish-action" :to="`/itineraries/${props.itineraryId}/publish-field-note`"><Send :size="15" />发布笔记</RouterLink ><button v-if="store.accessRole === 'owner'" class="icon-action" type="button" title="导出 DOCX" aria-label="导出 DOCX" :disabled="loadingVersions" @click="openExport"><FileDown :size="17" /></button ><button v-if="store.accessRole === 'owner'" class="icon-action" type="button" title="Share itinerary" aria-label="Share itinerary" @click="sharing = true"><Share2 :size="17" /></button><details v-if="store.accessRole === 'owner'" class="more-actions"><summary class="icon-action" title="更多计划操作" aria-label="更多计划操作"><MoreHorizontal :size="18" /></summary><button type="button" @click="openItineraryDeletion"><Trash2 :size="15" />删除计划</button></details></div></header><section v-if="store.state === 'conflict'" class="notice conflict" role="alert"><CircleAlert :size="18" /><div><strong>这份计划在别处发生了变化。</strong><span>刷新页面后再继续编辑，避免覆盖同行人的安排。</span></div><button type="button" @click="reloadWorkspace">刷新</button></section><section v-else-if="store.state === 'unavailable'" class="notice unavailable" role="alert"><CircleAlert :size="18" /><div><strong>部分外部服务暂不可用。</strong><span>你已经保存的行程内容仍然保留，可以继续查看计划。</span></div></section><Transition name="fade"><section v-if="!store.canEdit && store.state !== 'loading'" class="notice readonly" role="status"><LockKeyhole :size="18" /><div><strong>你正在以只读身份查看此行程。</strong><span>浏览者可以查看路线和备注，只有拥有者或编辑者可以修改内容。</span></div></section></Transition><Transition name="fade"><p v-if="actionError" class="action-error" role="alert"> {{ actionError }} </p></Transition><section v-if="store.canEdit && !companionLoading" class="companion-strip"><template v-if="!companionWorkspace && store.accessRole === 'owner'" ><div><p class="workspace-label">COMPANION PLAN</p><strong>让这份路线找到同行的人。</strong><span>发布后进入审核，成员加入后可一起调整路线。</span></div><RouterLink class="companion-command" :to="`/itineraries/${props.itineraryId}/publish-companion-plan`"><Users :size="16" />发起同行计划</RouterLink></template ><template v-else-if="companionWorkspace" ><div><p class="workspace-label">COMPANION / {{ companionWorkspace.status }}</p><strong>{{ companionWorkspace.role === 'member' ? '同行协作中' : companionWorkspace.role === 'owner' ? '同行计划进行中' : '这份路线已有关联同行计划' }}</strong ><span>{{ companionWorkspace.accepted_count }} / {{ companionWorkspace.party_size }} 人 · {{ companionWorkspace.status }}</span></div><div class="companion-actions"><button v-if="companionWorkspace.conversation_id" type="button" @click="router.push(`/messages/${companionWorkspace!.conversation_id}`)"><MessageCircle :size="16" />进入群聊</button><button v-if="companionWorkspace.role === 'owner' && companionWorkspace.review_status === 'approved' && companionWorkspace.status === 'open'" type="button" :disabled="companionBusy" @click="transitionCompanion('close')">关闭招募</button><button v-if="companionWorkspace.role === 'owner' && companionWorkspace.review_status === 'approved' && companionWorkspace.status !== 'completed'" class="quiet" type="button" :disabled="companionBusy" @click="transitionCompanion('complete')">结束同行</button></div></template ></section><section v-if="store.state === 'loading'" class="state-panel"><div class="skeleton-line"></div><div class="skeleton-line short"></div><span>正在读取这份路线。</span></section><section v-else-if="!hasDays" class="empty-workspace"><div class="empty-mark"><CalendarPlus :size="27" /></div><p class="workspace-label">FIRST DAY</p><h2> {{ store.canEdit ? '先把第一天放进来。' : '这份行程还没有安排。' }} </h2><p>计划已经建立，接下来给它一个日期，地点和顺序会在这里展开。</p><button v-if="store.canEdit" class="primary-action" type="button" :disabled="addingDay" @click="addDay"><CalendarPlus :size="16" />{{ addingDay ? '正在加入' : '加入第一天' }}</button></section><section v-else class="workspace-board" data-reveal><aside class="day-rail"><div class="rail-top"><span>ROUTE DAYS</span ><button v-if="store.canEdit" type="button" title="Add day" aria-label="Add day" :disabled="addingDay" @click="addDay"><CalendarPlus :size="16" /></button></div><label v-if="store.canEdit" class="day-picker">新增日期<input v-model="newDayDate" type="date" /><button type="button" :disabled="addingDay" @click="addDay">加入</button></label><nav aria-label="行程日期"><div v-for="(item, index) in store.snapshot?.days" :key="item.id" class="day-entry" :class="{ selected: activeDay === index }"><button class="day-select" type="button" @click=" activeDay = index; selectedEventId = '' " ><span>DAY {{ String(index + 1).padStart(2, '0') }}</span ><strong>{{ new Date(`${item.day_date}T00:00:00`).toLocaleDateString('zh-CN', { weekday: 'short' }) }}</strong ><small>{{ item.day_date.slice(5) }} · {{ item.events.length }} 站</small></button ><button v-if="store.canEdit && item.id" class="day-delete" type="button" title="删除这一天" aria-label="删除这一天" @click.stop="openDayRemoval(item.id)"><Trash2 :size="15" /></button></div></nav><div class="rail-footer"><span>{{ store.snapshot?.days.length }} 天</span><span>{{ store.snapshot?.start_date }} — {{ store.snapshot?.end_date }}</span></div></aside><section class="timeline-column"><header class="column-header"><div><p class="workspace-label"> DAY {{ String(activeDay + 1).padStart(2, '0') }} / {{ dayLabel }} </p><h2>时间线</h2></div><button v-if="store.canEdit" class="route-refresh" type="button" :disabled="store.routeUpdating" @click="refreshRoute"><MapPinned :size="15" />{{ store.routeUpdating ? '正在更新' : '刷新路线' }}</button></header><template v-if="store.canEdit" ><div class="poi-search"><label>搜索地点<input v-model="poiQuery" type="search" placeholder="例如：西湖、杭州东站、知味观" @keyup.enter="searchPlaces" /></label><button type="button" :disabled="searchingPOIs || !poiQuery.trim()" @click="searchPlaces"><Search :size="15" />{{ searchingPOIs ? '搜索中' : '搜索' }}</button></div><div v-if="poiResults.length" class="poi-results"><TransitionGroup name="list" tag="div" class="poi-results-list"><article v-for="poi in poiResults" :key="poi.id"><div><strong>{{ poi.name }}</strong ><small>{{ poi.address || poi.city || '高德已验证地点' }}</small></div><button type="button" :disabled="addingPOIId === poi.id" @click="addPlace(poi)"><Plus :size="15" />{{ addingPOIId === poi.id ? '加入中' : '加入当天' }}</button></article></TransitionGroup></div></template ><Timeline v-if="day" :day="day" :active="true" :readonly="!store.canEdit" :selected-event-id="selectedEventId" :busy-event-id="busyEventId" @select="selectEvent" @move="moveEvent" @remove="removeEvent" /><div v-if="!day?.events.length" class="timeline-hint"><MapPinned :size="17" /><div><strong>还没有地点。</strong><span>{{ store.canEdit ? '从上方搜索一个真实地点，将它加入当天路线。' : '拥有者或编辑者尚未将地点加入当天路线。' }}</span></div></div></section><aside class="context-column"><MapPanel :day="day" :updating="store.routeUpdating" :unavailable="store.state === 'unavailable'" @refresh="refreshRoute" /><section class="detail-panel"><header><div><p class="workspace-label">SELECTED PLACE</p><h2> {{ selectedEvent?.poi_snapshot.name || '选择一个地点' }} </h2></div><Save v-if="selectedEvent && store.canEdit" :size="17" /></header><template v-if="selectedEvent" ><p class="place-address"> {{ selectedEvent.poi_snapshot.address || '已验证地点' }} </p><label>给这一站留一句话<textarea v-model="notesDraft" rows="4" :readonly="!store.canEdit" placeholder="比如：下午四点以后光线更好"></textarea></label ><button v-if="store.canEdit" class="save-notes" type="button" :disabled="savingNotes" @click="saveNotes"> {{ savingNotes ? '正在保存' : '保存备注' }} </button></template ><div v-else class="detail-empty"><MapPinned :size="20" /><span>搜索并加入地点后，可在这里补充备注。</span></div></section><section class="detail-panel trip-support"><TripSupportPanel :itinerary-id="props.itineraryId" :can-edit="store.canEdit" /></section></aside></section><footer v-if="store.state === 'saved' && hasDays" class="workspace-footer" data-reveal><span>版本 {{ store.version }} · 地点顺序由你决定</span><span>当前日期 {{ dayLabel }}</span></footer><Transition name="fade"><div v-if="exporting && store.accessRole === 'owner'" class="share-overlay export-overlay" role="dialog" aria-modal="true" aria-label="导出 DOCX"><section><header><div><p class="workspace-label">PRIVATE DOCUMENT</p><h2>导出 DOCX</h2></div><button type="button" title="关闭" aria-label="关闭" @click="closeExport"><X :size="18" /></button></header><label class="export-version" >导出版本<select v-model.number="selectedExportVersion" :disabled="exportStore.state !== 'idle' && exportStore.state !== 'unavailable'"><option v-for="version in exportVersions" :key="version.id" :value="version.version_no">版本 {{ version.version_no }}</option></select></label ><p class="export-copy"> 将导出已保存的版本 {{ selectedExportVersion ?? '...' }}。文件生成后才会请求一次性下载链接。 </p><div class="export-status" :class="exportStore.state"><span class="export-status-icon"><FileDown v-if="exportStore.state === 'idle' || exportStore.state === 'submitting' || exportStore.state === 'queued' || exportStore.state === 'running'" :size="18" /><Check v-else-if="exportStore.state === 'succeeded'" :size="18" /><CircleAlert v-else :size="18" /></span><div><strong>{{ exportStore.state === 'idle' ? '准备导出' : exportStore.state === 'submitting' ? '正在提交导出' : exportStore.state === 'queued' ? '已进入队列' : exportStore.state === 'running' ? '正在生成文档' : exportStore.state === 'succeeded' ? 'DOCX 已生成' : exportStore.state === 'failed' ? 'DOCX 生成失败' : '导出暂不可用' }}</strong ><small v-if="exportStore.task && (exportStore.state === 'queued' || exportStore.state === 'running')">进度 {{ exportStore.task.progress }}%</small><small v-else>{{ exportStore.message || (exportStore.state === 'succeeded' ? '下载链接将在你点击下载时创建。' : '文件将包含此版本的路线与备注。') }}</small></div></div><div class="export-actions"><button v-if="exportStore.state === 'idle' || exportStore.state === 'unavailable'" class="export-primary" type="button" :disabled="store.state === 'loading' || selectedExportVersion === null" @click="createExport"><FileDown :size="16" />生成 DOCX</button><button v-else-if="exportStore.canRetry" class="export-primary" type="button" @click="exportStore.retry"><RefreshCw :size="16" />重新生成</button><button v-else-if="exportStore.state === 'succeeded'" class="export-primary" type="button" :disabled="exportStore.downloading" @click="exportStore.download"><Download :size="16" />{{ exportStore.downloading ? '正在打开下载' : '下载 DOCX' }}</button></div></section></div></Transition><Transition name="fade"><div v-if="sharing" class="share-overlay" role="dialog" aria-modal="true" aria-label="分享行程"><section><header><div><p class="workspace-label">COLLABORATION</p><h2>分享与协作</h2></div><button type="button" title="关闭" aria-label="关闭" @click="sharing = false"><X :size="18" /></button></header><div class="share-row"><div><strong>只读分享链接</strong><small>任何持有链接的人都只能查看行程。</small></div><button type="button" :disabled="creatingShare" @click="createShareLink"><Link :size="15" />{{ creatingShare ? '创建中' : '创建链接' }}</button></div><div v-if="shareUrl" class="copy-row"><input :value="shareUrl" readonly /><button type="button" @click="copy(shareUrl)">复制</button></div><form class="invite-form" @submit.prevent="createInvitation"><div><strong>邀请协作者</strong><small>使用已注册用户的 UUID；编辑者可修改，浏览者只能查看。</small></div><input v-model="inviteUserId" required placeholder="用户 UUID" /><select v-model="inviteRole"><option value="editor">编辑者</option><option value="viewer">浏览者</option></select ><button type="submit" :disabled="inviting"><UserPlus :size="15" />{{ inviting ? '邀请中' : '创建邀请' }}</button></form><div v-if="inviteUrl" class="copy-row"><input :value="inviteUrl" readonly /><button type="button" @click="copy(inviteUrl)">复制邀请</button></div><p v-if="shareError" class="share-error" role="alert"> {{ shareError }} </p></section></div></Transition><Transition name="fade"><div v-if="removeDayId && dayPendingRemoval" class="share-overlay" role="dialog" aria-modal="true" aria-labelledby="remove-day-title"><section class="delete-dialog"><header><div><p class="workspace-label">DAY REMOVAL</p><h2 id="remove-day-title">删除这一天</h2></div><button type="button" title="关闭" aria-label="关闭" :disabled="deletingDay" @click="closeDayRemoval"><X :size="18" /></button></header><p>这一天的地点、路线和计算记录将被永久删除。</p><p v-if="deletionError" class="share-error" role="alert"> {{ deletionError }} </p><footer><button type="button" :disabled="deletingDay" @click="closeDayRemoval">取消</button ><button class="delete-confirm" type="button" :disabled="deletingDay" @click="confirmDayRemoval"> {{ deletingDay ? '正在删除' : '删除这一天' }} </button></footer></section></div></Transition><Transition name="fade"><div v-if="deleteItineraryOpen && store.accessRole === 'owner'" class="share-overlay" role="dialog" aria-modal="true" aria-labelledby="delete-itinerary-title"><section class="delete-dialog"><header><div><p class="workspace-label">PERMANENT DELETE</p><h2 id="delete-itinerary-title">删除计划</h2></div><button type="button" title="关闭" aria-label="关闭" :disabled="deletingItinerary" @click="closeItineraryDeletion"><X :size="18" /></button></header><p>此操作会永久删除“{{ store.snapshot?.title }}”及其所有路线内容，且无法撤销。请确认是否继续。</p><p v-if="deletionError" class="share-error" role="alert"> {{ deletionError }} </p><footer><button type="button" :disabled="deletingItinerary" @click="closeItineraryDeletion">取消</button ><button class="delete-confirm" type="button" :disabled="deletingItinerary" @click="confirmItineraryDeletion"> {{ deletingItinerary ? '正在删除' : '永久删除' }} </button></footer></section></div></Transition></template></main></template>

<style scoped>.workspace{background:var(--field-paper);color:var(--field-ink);min-height:calc(100vh - 70px);padding:28px clamp(18px,3vw,48px) 38px}.workspace-header{align-items:end;border-bottom:1px solid var(--field-line);display:flex;justify-content:space-between;gap:24px;margin:0 auto;max-width:1480px;padding-bottom:23px}.header-left{align-items:start;display:flex;gap:30px}.back-link{align-items:center;color:var(--field-teal);display:inline-flex;font-size:12px;font-weight:800;gap:6px;padding-top:4px;text-decoration:none;white-space:nowrap}.title-block{border-left:1px solid var(--field-line);padding-left:30px}.workspace-label{color:var(--field-teal);font:800 10px/1.2 var(--field-mono);letter-spacing:.09em;margin:0 0 9px}.title-block h1{font-size:34px;letter-spacing:-.025em;line-height:1;margin:0}.header-actions{align-items:center;display:flex;gap:10px}.save-indicator{align-items:center;color:var(--field-teal);display:inline-flex;font:700 11px var(--field-mono);gap:5px;margin-right:8px}.save-indicator.conflict{color:var(--field-coral)}.save-indicator.loading{color:var(--field-muted)}.save-indicator.unavailable{color:var(--field-saffron)}.icon-action{align-items:center;background:#fff;border:1px solid var(--field-line);color:var(--field-ink-soft);cursor:pointer;display:inline-flex;padding:9px}.icon-action:hover{border-color:var(--field-teal);color:var(--field-teal)}.notice{align-items:center;display:flex;gap:12px;margin:18px auto 0;max-width:1480px;padding:13px 15px}.notice>svg{flex:0 0 auto}.notice div{display:grid;gap:4px}.notice span{color:inherit;font-size:12px;opacity:.78}.notice button{background:transparent;border:1px solid currentColor;color:inherit;cursor:pointer;font-weight:800;margin-left:auto;padding:7px 11px}.conflict{background:#f8ded8;color:#8e3329}.unavailable{background:#fff0cc;color:#855f14}.action-error{background:#fff0cc;color:#855f14;font-size:12px;margin:18px auto 0;max-width:1480px;padding:11px 13px}.state-panel{background:#fff;display:grid;gap:12px;margin:28px auto;max-width:1480px;min-height:320px;padding:60px;place-content:center;text-align:center}.skeleton-line{animation:pulse 1.3s ease-in-out infinite;background:#dce7e5;height:14px;width:240px}.skeleton-line.short{width:150px}.state-panel span{color:var(--field-muted);font-size:13px}.empty-workspace{background:#fff;margin:30px auto;max-width:760px;padding:86px 50px;text-align:center}.empty-mark{align-items:center;background:var(--field-teal-soft);color:var(--field-teal);display:inline-flex;height:58px;justify-content:center;width:58px}.empty-workspace .workspace-label{margin-top:24px}.empty-workspace h2{font-size:32px;margin:0}.empty-workspace p:not(.workspace-label){color:var(--field-muted);line-height:1.6;margin:13px auto 26px;max-width:420px}.primary-action{align-items:center;background:var(--field-deep);border:0;color:#fff;cursor:pointer;display:inline-flex;font-weight:800;gap:8px;padding:13px 16px}.primary-action:hover{background:var(--field-teal)}.primary-action:disabled{cursor:wait;opacity:.62}.workspace-board{display:grid;grid-template-columns:184px minmax(380px,1fr) minmax(330px,.82fr);margin:25px auto 0;max-width:1480px;min-height:620px}.day-rail{background:var(--field-deep);color:#fff;display:flex;flex-direction:column}.rail-top{align-items:center;color:#a9c8c5;display:flex;font:10px var(--field-mono);justify-content:space-between;letter-spacing:.08em;padding:18px 16px 13px}.rail-top button{align-items:center;background:#2a5b66;border:0;color:#fff;cursor:pointer;display:inline-flex;padding:6px}.rail-top button:disabled{cursor:wait;opacity:.5}.day-rail nav{display:grid;gap:1px}.day-rail nav button{background:transparent;border:0;color:#b8ced0;cursor:pointer;display:grid;gap:6px;padding:17px 16px;text-align:left}.day-rail nav button:hover{background:#1c4653}.day-rail nav button.selected{background:var(--field-paper);color:var(--field-ink)}.day-rail nav button span{color:var(--field-saffron);font:800 10px var(--field-mono)}.day-rail nav button strong{font-size:16px}.day-rail nav button small{font-size:11px;opacity:.78}.rail-footer{border-top:1px solid #335967;display:grid;gap:6px;margin-top:auto;padding:16px}.rail-footer span:first-child{color:#fff;font-weight:800}.rail-footer span:last-child{color:#9bb8bc;font:10px var(--field-mono);line-height:1.4}.timeline-column{background:#fff;min-width:0;padding:26px clamp(20px,3vw,40px)}.column-header{align-items:end;border-bottom:1px solid var(--field-line);display:flex;justify-content:space-between;gap:16px;padding-bottom:19px}.column-header h2{font-size:24px;margin:0}.route-refresh{align-items:center;background:var(--field-teal-soft);border:0;color:var(--field-teal);cursor:pointer;display:inline-flex;font-size:12px;font-weight:800;gap:7px;padding:9px 10px}.route-refresh:disabled{cursor:wait;opacity:.55}.timeline-hint{align-items:start;background:#eff5f2;color:var(--field-teal);display:flex;gap:11px;margin-top:18px;padding:15px}.timeline-hint div{display:grid;gap:5px}.timeline-hint span{color:var(--field-muted);font-size:12px;line-height:1.45}.context-column{background:#e6efeb;min-width:0}.detail-panel{background:#fff;margin:14px;padding:19px}.detail-panel header{align-items:start;display:flex;justify-content:space-between}.detail-panel header svg{color:var(--field-teal)}.detail-panel h2{font-size:20px;margin:0}.place-address{color:var(--field-muted);font-size:12px;margin:10px 0 20px}.detail-panel label{color:var(--field-ink-soft);display:grid;font-size:12px;font-weight:800;gap:8px}.detail-panel textarea{border:1px solid var(--field-line);color:var(--field-ink);padding:10px;resize:vertical}.save-notes{background:var(--field-deep);border:0;color:#fff;cursor:pointer;font-size:12px;font-weight:800;margin-top:10px;padding:10px 12px}.save-notes:hover{background:var(--field-teal)}.save-notes:disabled{cursor:wait;opacity:.6}.detail-empty{align-items:center;color:var(--field-muted);display:flex;gap:10px;line-height:1.5;min-height:72px}.detail-empty svg{color:var(--field-teal);flex:0 0 auto}.workspace-footer{color:var(--field-muted);display:flex;font:11px var(--field-mono);justify-content:space-between;margin:16px auto 0;max-width:1480px}.back-link:hover{color:var(--field-ink)}.poi-search{align-items:end;border-bottom:1px solid var(--field-line);display:grid;gap:9px;grid-template-columns:1fr auto;padding:16px 0}.poi-search label{color:var(--field-ink-soft);display:grid;font-size:12px;font-weight:800;gap:6px}.poi-search input{border:1px solid var(--field-line);color:var(--field-ink);min-height:39px;padding:8px 10px}.poi-search button,.poi-results button{align-items:center;background:var(--field-deep);border:0;color:#fff;cursor:pointer;display:inline-flex;font-size:12px;font-weight:800;gap:6px;min-height:39px;padding:8px 10px}.poi-search button:disabled,.poi-results button:disabled{cursor:wait;opacity:.55}.poi-results{border-bottom:1px solid var(--field-line);display:grid;max-height:235px;overflow:auto}.poi-results article{align-items:center;border-top:1px solid var(--field-line);display:flex;gap:12px;justify-content:space-between;padding:11px 0}.poi-results article:first-child{border-top:0}.poi-results article>div{display:grid;gap:4px;min-width:0}.poi-results strong{font-size:13px}.poi-results small{color:var(--field-muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.poi-results button{background:var(--field-teal);flex:0 0 auto;min-height:34px}.day-picker{border-bottom:1px solid var(--field-line);color:var(--field-ink-soft);display:grid;font-size:11px;font-weight:800;gap:6px;padding:12px}.day-picker input{border:1px solid var(--field-line);color:var(--field-ink);min-height:34px;padding:6px}.day-picker button{background:var(--field-teal);border:0;color:#fff;cursor:pointer;font-size:12px;font-weight:800;min-height:32px}.readonly{background:#e5eef0;color:#285867}.share-overlay{align-items:center;background:#1426387a;display:flex;inset:0;justify-content:center;padding:20px;position:fixed;z-index:20}.share-overlay>section{background:var(--field-paper);box-shadow:0 20px 54px #1426383d;display:grid;gap:18px;max-width:560px;padding:24px;width:min(100%,560px)}.share-overlay header{align-items:start;display:flex;justify-content:space-between}.share-overlay h2{margin:0}.share-overlay header button{background:transparent;border:0;color:var(--field-muted);cursor:pointer;padding:4px}.share-row,.invite-form{border-top:1px solid var(--field-line);display:grid;gap:10px;padding-top:17px}.share-row>div,.invite-form>div{display:grid;gap:4px}.share-row small,.invite-form small{color:var(--field-muted);font-size:12px;line-height:1.45}.share-row>button,.invite-form>button,.copy-row button{align-items:center;background:var(--field-deep);border:0;color:#fff;cursor:pointer;display:inline-flex;font-size:12px;font-weight:800;gap:6px;justify-content:center;min-height:38px;padding:8px 11px}.share-row>button{justify-self:start}.copy-row{display:grid;gap:8px;grid-template-columns:minmax(0,1fr) auto}.copy-row input,.invite-form input,.invite-form select{background:#fff;border:1px solid var(--field-line);color:var(--field-ink);min-height:38px;min-width:0;padding:8px 10px}.invite-form{grid-template-columns:minmax(0,1fr) 108px auto}.invite-form>div{grid-column:1 / -1}.share-error{color:#8e3329;font-size:12px;margin:0}.export-copy{color:var(--field-ink-soft);font-size:13px;line-height:1.5;margin:0}.export-status{align-items:center;border-bottom:1px solid var(--field-line);border-top:1px solid var(--field-line);display:flex;gap:12px;padding:15px 0}.export-status-icon{align-items:center;background:#e5eef0;color:var(--field-teal);display:inline-flex;flex:0 0 38px;height:38px;justify-content:center}.export-status>div{display:grid;gap:4px}.export-status small{color:var(--field-muted);font-size:12px;line-height:1.4}.export-status.succeeded .export-status-icon{background:#dceee9;color:#236753}.export-status.failed .export-status-icon,.export-status.unavailable .export-status-icon{background:#f8ded8;color:#8e3329}.export-actions{display:flex;justify-content:flex-end}.export-primary{align-items:center;background:var(--field-deep);border:0;color:#fff;cursor:pointer;display:inline-flex;font-size:12px;font-weight:800;gap:7px;min-height:40px;padding:9px 13px}.export-primary:disabled{cursor:wait;opacity:.55}.icon-action:focus-visible,.export-primary:focus-visible,.share-overlay header button:focus-visible,.publish-action:focus-visible,.source-link:focus-visible{outline:3px solid var(--field-saffron);outline-offset:3px}.source-link{color:var(--field-teal);display:inline-block;font:800 11px var(--field-mono);margin-top:10px;text-decoration:none}.publish-action{align-items:center;background:var(--field-coral);color:#fff;display:inline-flex;font:800 12px var(--field-mono);gap:6px;min-height:38px;padding:8px 11px;text-decoration:none}.companion-strip{align-items:center;background:#edf7f2;border:1px solid var(--travel-line);display:flex;gap:18px;justify-content:space-between;margin:18px auto 0;max-width:1480px;padding:14px 16px}.companion-strip>div:first-child{display:grid;gap:4px}.companion-strip .workspace-label{margin:0}.companion-strip strong{font-size:14px}.companion-strip span{color:var(--field-muted);font-size:12px}.companion-command,.companion-actions button{align-items:center;background:var(--travel-sea);border:0;color:#fff;cursor:pointer;display:inline-flex;font-size:12px;font-weight:800;gap:6px;justify-content:center;min-height:38px;padding:8px 11px;text-decoration:none}.companion-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}.companion-actions .quiet{background:transparent;border:1px solid var(--travel-sea);color:var(--travel-sea)}.companion-actions button:disabled{cursor:wait;opacity:.55}@keyframes pulse{0%,to{opacity:.55}50%{opacity:1}}.export-version{color:var(--field-ink-soft);display:grid;font-size:12px;font-weight:800;gap:6px}.export-version select{background:#fff;border:1px solid var(--field-line);color:var(--field-ink);min-height:38px;padding:8px 10px}.more-actions{position:relative}.more-actions summary{list-style:none}.more-actions summary::-webkit-details-marker{display:none}.more-actions>button{align-items:center;background:#fff;border:1px solid var(--field-line);color:#9c4234;cursor:pointer;display:flex;font:800 12px var(--field-mono);gap:7px;min-height:38px;padding:8px 11px;position:absolute;right:0;top:45px;white-space:nowrap;z-index:5}.more-actions>button:hover{background:#fff0eb}.day-entry{border-bottom:1px solid var(--field-line);display:grid;grid-template-columns:minmax(0,1fr) auto}.day-entry.selected{background:var(--field-teal);color:#fff}.day-select{background:transparent;border:0;color:inherit;cursor:pointer;display:grid;gap:4px;min-width:0;padding:14px 12px;text-align:left}.day-select span,.day-select small{font-size:10px}.day-select small{color:var(--field-muted)}.day-entry.selected .day-select small{color:#d9f2e7}.day-delete{align-self:center;background:transparent;border:0;color:var(--field-coral);cursor:pointer;display:inline-flex;margin-right:7px;padding:7px}.day-entry.selected .day-delete{color:#fff}.day-delete:hover{background:#ffffff2e}.delete-dialog{max-width:500px}.delete-dialog>p{color:var(--field-ink-soft);font-size:13px;line-height:1.55;margin:0}.delete-dialog>label{color:var(--field-ink-soft);display:grid;font-size:12px;font-weight:800;gap:7px}.delete-dialog input{background:#fff;border:1px solid var(--field-line);color:var(--field-ink);font:inherit;min-height:40px;padding:8px 10px}.delete-dialog footer{display:flex;gap:9px;justify-content:flex-end}.delete-dialog footer button{background:#fff;border:1px solid var(--field-line);color:var(--field-ink);cursor:pointer;font:800 12px var(--field-mono);min-height:39px;padding:8px 12px}.delete-dialog footer .delete-confirm{background:#a63e31;border-color:#a63e31;color:#fff}.delete-dialog button:disabled{cursor:wait;opacity:.55}.day-delete:focus-visible,.more-actions summary:focus-visible,.more-actions>button:focus-visible,.delete-dialog button:focus-visible,.delete-dialog input:focus-visible{outline:3px solid var(--field-saffron);outline-offset:3px}@media(max-width:1080px){.workspace-board{grid-template-columns:150px minmax(340px,1fr)}.context-column{grid-column:1 / -1;display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,.8fr)}.map-panel,.terrain{min-height:360px}}@media(max-width:720px){.workspace{padding:20px 14px 30px}.workspace-header{align-items:start;flex-direction:column}.header-left{flex-direction:column;gap:18px}.title-block{border-left:0;border-top:1px solid var(--field-line);padding-left:0;padding-top:18px}.header-actions{align-self:stretch;justify-content:space-between}.companion-strip{align-items:stretch;flex-direction:column}.companion-command,.companion-actions button{flex:1}.companion-actions{justify-content:stretch}.workspace-board{grid-template-columns:1fr}.day-rail{min-height:0}.day-rail nav{display:flex;overflow-x:auto}.day-entry{flex:0 0 142px}.day-select{min-width:0}.rail-footer{display:none}.context-column{display:block}.map-panel,.terrain{min-height:340px}.workspace-footer{align-items:start;flex-direction:column;gap:7px}.empty-workspace{padding:58px 24px}.invite-form,.copy-row{grid-template-columns:1fr}.share-row>button{width:100%}.delete-dialog footer{display:grid;grid-template-columns:1fr 1fr}}@media(prefers-reduced-motion:reduce){.skeleton-line{animation:none}}.access-panel{align-items:start;display:grid;gap:12px;margin:64px auto;max-width:520px;padding:26px 0}.access-panel>svg{color:var(--field-coral)}.access-panel h1{font-size:30px;letter-spacing:0;margin:0}.access-panel>p:not(.workspace-label){color:var(--field-ink-soft);line-height:1.55;margin:0}.access-panel .primary-action{justify-self:start;text-decoration:none}.workspace{--travel-ink: #17343b;--travel-muted: #63787b;--travel-line: #d7e5df;--travel-sea: #087b78;--travel-coral: #e96d52;--travel-mint: #edf7f2;background:linear-gradient(135deg,#f7fcf8,#fffdf9 62%,#f0f8f4);color:var(--travel-ink);padding:clamp(22px,3vw,48px) clamp(14px,3vw,52px) 42px}.workspace-header{border-bottom:2px solid var(--travel-ink);padding-bottom:25px}.back-link{color:var(--travel-sea)}.title-block{border-left-color:var(--travel-line)}.workspace-label{color:var(--travel-coral)}.title-block h1{font-family:Georgia,"Noto Serif SC",serif;font-size:clamp(30px,3vw,43px);font-weight:600;letter-spacing:0}.save-indicator{background:var(--travel-mint);border-radius:999px;color:var(--travel-sea);padding:7px 9px}.icon-action{background:#fff;border-color:#c9ddd5;border-radius:50%;color:var(--travel-ink);height:38px;justify-content:center;width:38px}.icon-action:hover{background:var(--travel-mint);border-color:var(--travel-sea)}.notice{border-radius:9px}.conflict{background:#fff0eb;color:#9c4234}.unavailable{background:#fff8df;color:#805d16}.readonly{background:#e9f5f0;color:#28665e}.action-error{background:#fff0eb;border-left:3px solid var(--travel-coral);color:#9c4234;padding:10px 12px}.workspace-board{border:1px solid var(--travel-line);border-radius:14px;box-shadow:0 18px 44px #104c4314;overflow:hidden}.day-rail{background:#f1f8f4;border-right-color:var(--travel-line)}.rail-top{border-bottom-color:var(--travel-line);color:var(--travel-coral)}.rail-top button{background:var(--travel-sea);border-radius:50%;color:#fff}.day-rail nav button{border-bottom-color:var(--travel-line);color:var(--travel-ink)}.day-rail nav button:hover{background:#e3f2ea}.day-rail nav button.selected{background:var(--travel-sea);color:#fff}.day-rail nav button.selected small{color:#d9f2e7}.rail-footer{border-top-color:var(--travel-line);color:var(--travel-muted)}.timeline-column,.context-column{background:#fff}.timeline-column{padding:clamp(17px,2.5vw,30px)}.column-header{border-bottom-color:var(--travel-line)}.column-header h2,.detail-panel h2{font-family:Georgia,"Noto Serif SC",serif;font-size:26px;font-weight:600;letter-spacing:0}.route-refresh{background:#e4f4ec;border-radius:999px;color:var(--travel-sea)}.poi-search{border-bottom-color:var(--travel-line)}.poi-search input{background:#fcfffd;border-color:#c9ddd5;border-radius:7px}.poi-search button,.poi-results button{background:var(--travel-sea);border-radius:7px}.poi-results{border-bottom-color:var(--travel-line)}.poi-results article{border-top-color:var(--travel-line)}.timeline-hint{background:#f1f8f4;border:1px dashed #b8d6c8;border-radius:10px}.detail-panel{border-top-color:var(--travel-line);padding:22px}.detail-panel header{border-bottom-color:var(--travel-line)}.detail-panel textarea{background:#fcfffd;border-color:#c9ddd5;border-radius:8px}.save-notes{background:var(--travel-sea);border-radius:999px}.detail-empty{background:#f3faf6;border-radius:9px}.workspace-footer{color:var(--travel-muted)}.empty-workspace,.state-panel{background:transparent;border:1px dashed #b8d6c8;border-radius:14px}.empty-workspace h2{font-family:Georgia,"Noto Serif SC",serif;letter-spacing:0}.empty-mark{background:#e1f2ea;color:var(--travel-sea)}.primary-action{background:var(--travel-sea);border-radius:999px;box-shadow:0 9px 20px #087b7829}.share-overlay{background:#17343b6b;backdrop-filter:blur(6px)}.share-overlay>section{border:1px solid var(--travel-line);border-radius:14px;box-shadow:0 22px 64px #104c4333}.share-row,.invite-form,.export-status{border-color:var(--travel-line)}.share-row>button,.invite-form>button,.copy-row button,.export-primary{background:var(--travel-sea);border-radius:999px}.copy-row input,.invite-form input,.invite-form select,.export-version select{border-color:#c9ddd5;border-radius:7px}.export-status-icon{background:#e3f3ed;color:var(--travel-sea)}@media(max-width:720px){.workspace-board{border-radius:10px}.header-actions{gap:7px}.save-indicator{margin-right:auto}.timeline-column{padding:18px 14px}.detail-panel{padding:20px 16px}}</style>
