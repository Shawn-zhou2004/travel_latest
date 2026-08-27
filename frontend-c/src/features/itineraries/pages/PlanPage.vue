<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Check, CircleAlert, CircleCheck, LoaderCircle, MapPinned, Plus, RefreshCw, Search, SearchX, Sparkles, X } from 'lucide-vue-next'
import { normalizeApiError } from '@/services/api'
import { getMySettings, type TravelerType, type UserSettings } from '@/features/settings/api'
import { createManualPlan, searchDestinations, type DestinationOption, type PreferenceTag } from '../destinationsApi'
import { searchPOIs, type POIRecord } from '../api'
import { useAiPlanningStore } from '../stores/aiPlanning'
import { useReveal } from '@/composables/useReveal'

const preferences: PreferenceTag[] = ['经典必玩', '吃吃喝喝', '小众探索', '拍照出片', '逛街购物', 'citywalk', '自然风光', '文艺展览', '历史古建']
const router = useRouter()
const route = useRoute()
const planning = useAiPlanningStore()
planning.reset()
const deepLinkJobId = typeof route.query.jobId === 'string' ? route.query.jobId : ''
const deepLinkActive = ref(deepLinkJobId !== '')

const destinationQuery = ref('')
const selectedDestination = ref<DestinationOption | null>(null)
const destinationResults = ref<DestinationOption[]>([])
const destinationOpen = ref(false)
const destinationLoading = ref(false)
const activeOption = ref(-1)
const startDate = ref('')
const endDate = ref('')
const selectedTags = ref<PreferenceTag[]>([])
const selectedPace = ref<'slow' | 'balanced' | 'fast' | null>(null)
const selectedTravelerType = ref<TravelerType | null>(null)
const savedSettings = ref<UserSettings | null>(null)
const tagsTouched = ref(false)
const paceTouched = ref(false)
const travelerTypeTouched = ref(false)
const prompt = ref('')
const mustVisitQuery = ref('')
const mustVisitResults = ref<POIRecord[]>([])
const mustVisitLoading = ref(false)
const mustVisitPoi = ref<POIRecord[]>([])
const manualCreating = ref(false)
const formError = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchSequence = 0
const root = ref<HTMLElement | null>(null)
useReveal(root)

const durationDays = computed(() => {
  if (!startDate.value || !endDate.value) return null
  const start = new Date(`${startDate.value}T00:00:00`).getTime()
  const end = new Date(`${endDate.value}T00:00:00`).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return Math.round((end - start) / 86400000) + 1
})

const duration = computed(() => durationDays.value === null ? '选择日期后显示天数' : durationDays.value > 0 ? `${durationDays.value} 天` : '日期顺序需要调整')
const today = new Date().toISOString().slice(0, 10)

function clearSearch() {
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  searchTimer = undefined
  searchSequence += 1
  destinationLoading.value = false
}

function onDestinationInput() {
  formError.value = ''
  if (selectedDestination.value?.name !== destinationQuery.value) selectedDestination.value = null
  clearSearch()
  const query = destinationQuery.value.trim()
  if (!query) {
    destinationResults.value = []
    destinationOpen.value = false
    activeOption.value = -1
    return
  }
  destinationOpen.value = true
  destinationResults.value = []
  const request = searchSequence
  searchTimer = setTimeout(async () => {
    destinationLoading.value = true
    try {
      const results = await searchDestinations(query)
      if (request !== searchSequence) return
      destinationResults.value = results
      activeOption.value = results.length ? 0 : -1
    } catch (cause) {
      if (request !== searchSequence) return
      formError.value = normalizeApiError(cause).message
      destinationResults.value = []
    } finally {
      if (request === searchSequence) destinationLoading.value = false
    }
  }, 250)
}

function selectDestination(destination: DestinationOption) {
  selectedDestination.value = destination
  destinationQuery.value = destination.name
  destinationResults.value = []
  destinationOpen.value = false
  activeOption.value = -1
  formError.value = ''
}

function onDestinationKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' && destinationResults.value.length) {
    event.preventDefault()
    destinationOpen.value = true
    activeOption.value = (activeOption.value + 1 + destinationResults.value.length) % destinationResults.value.length
  } else if (event.key === 'ArrowUp' && destinationResults.value.length) {
    event.preventDefault()
    destinationOpen.value = true
    activeOption.value = (activeOption.value - 1 + destinationResults.value.length) % destinationResults.value.length
  } else if (event.key === 'Enter' && destinationOpen.value && activeOption.value >= 0) {
    event.preventDefault()
    selectDestination(destinationResults.value[activeOption.value])
  } else if (event.key === 'Escape') {
    destinationOpen.value = false
  }
}

function toggleTag(tag: PreferenceTag) {
  const index = selectedTags.value.indexOf(tag)
  if (index >= 0) {
    selectedTags.value.splice(index, 1)
    formError.value = ''
  } else if (selectedTags.value.length < 3) {
    selectedTags.value.push(tag)
    formError.value = ''
  } else {
    formError.value = '最多选择 3 个旅行偏好。'
  }
  tagsTouched.value = true
}

function clearTags() {
  selectedTags.value = []
  tagsTouched.value = true
  formError.value = ''
}

function setPace(value: 'slow' | 'balanced' | 'fast' | null) {
  selectedPace.value = value
  paceTouched.value = true
}

function setTravelerType(value: TravelerType | null) {
  selectedTravelerType.value = value
  travelerTypeTouched.value = true
}

function preferencesForRequest() {
  return {
    preference_tags: tagsTouched.value ? [...selectedTags.value] : undefined,
    pace: paceTouched.value ? selectedPace.value : undefined,
    traveler_type: travelerTypeTouched.value ? selectedTravelerType.value : undefined,
  }
}

function loadSettingsIntoForm(settings: UserSettings) {
  savedSettings.value = settings
  if (!tagsTouched.value) selectedTags.value = settings.interest_tags.slice(0, 3)
  if (!paceTouched.value) {
    const paceBySetting: Record<UserSettings['travel_pace'], 'slow' | 'balanced' | 'fast'> = { relaxed: 'slow', balanced: 'balanced', packed: 'fast' }
    selectedPace.value = paceBySetting[settings.travel_pace]
  }
  if (!travelerTypeTouched.value) selectedTravelerType.value = settings.traveler_type
}

function validate() {
  if (!selectedDestination.value) {
    formError.value = '请从搜索结果中选择目的地。'
    return false
  }
  if (!startDate.value || !endDate.value) {
    formError.value = '请选择完整的出行日期。'
    return false
  }
  if (startDate.value < today || durationDays.value === null || durationDays.value < 1 || durationDays.value > 7) {
    formError.value = '日期需要覆盖 1 到 7 天，开始日期不能早于今天。'
    return false
  }
  return true
}

async function createManual() {
  if (!validate() || manualCreating.value || !selectedDestination.value) return
  manualCreating.value = true
  formError.value = ''
  try {
    const itinerary = await createManualPlan({ destination: selectedDestination.value, start_date: startDate.value, end_date: endDate.value })
    await router.push(`/itineraries/${itinerary.id}`)
  } catch (cause) {
    formError.value = normalizeApiError(cause).message
  } finally {
    manualCreating.value = false
  }
}

async function createSmart() {
  if (!validate() || planning.isWorking || !selectedDestination.value) return
  formError.value = ''
  await planning.submit({
    destination: selectedDestination.value,
    start_date: startDate.value,
    end_date: endDate.value,
    prompt: prompt.value.trim(),
    must_visit_poi_ids: mustVisitPoi.value.map((poi) => poi.id),
    ...preferencesForRequest(),
  })
}

async function searchMustVisitPOIs() {
  if (!selectedDestination.value || !mustVisitQuery.value.trim() || mustVisitLoading.value) return
  mustVisitLoading.value = true
  try {
    mustVisitResults.value = await searchPOIs(mustVisitQuery.value.trim(), selectedDestination.value.city_code)
  } catch (cause) {
    formError.value = normalizeApiError(cause).message
  } finally {
    mustVisitLoading.value = false
  }
}

function addMustVisitPOI(poi: POIRecord) {
  if (mustVisitPoi.value.some((item) => item.id === poi.id)) return
  if (mustVisitPoi.value.length >= 6) {
    formError.value = '最多选择 6 个必去地点。'
    return
  }
  mustVisitPoi.value.push(poi)
  mustVisitQuery.value = ''
  mustVisitResults.value = []
}

function removeMustVisitPOI(poiId: string) {
  mustVisitPoi.value = mustVisitPoi.value.filter((poi) => poi.id !== poiId)
}

async function confirmPreview() {
  await planning.applyPreview()
  if (planning.appliedItineraryId) await router.push('/itineraries')
}

const generationStage = computed(() => {
  const labels: Record<string, string> = {
    queued: '正在排队等待规划', resolving_destination: '正在确认目的地', retrieving: '正在检索旅行资料',
    retrieving_reviewed_sources: '正在检索平台已审核资料', searching_live_sources: '正在补充本次实时网络资料',
    verifying_pois: '正在核验地点信息', planning: '正在生成行程方案', validating: '正在校验行程方案', awaiting_confirmation: '行程方案已生成，等待确认',
  }
  return planning.job ? (labels[planning.job.status] ?? '正在处理') : '正在建立任务'
})
const generationTitle = computed(() => ({ idle: '', submitting: '请求已收到。', queued: '路线正在排队。', progress: '正在把想法整理成路线。', ready: '来源可追溯的预览已准备好。', no_result: '这次没有找到可靠结果。', clarification: '还需要一个明确答案。', unavailable: '规划服务暂时不可用。' }[planning.state]))
const citationLabel = (sourceType: string) => sourceType === 'live_web' ? '本次实时网络资料' : '平台已审核资料'
const progressSteps = [
  { status: 'understanding', label: '理解需求' },
  { status: 'retrieving', label: '检索资料' },
  { status: 'verifying_pois', label: '核验地点' },
  { status: 'planning', label: '生成方案' },
  { status: 'validating', label: '校验预览' },
] as const
const currentProgressStep = computed(() => {
  const status = planning.job?.status
  if (status === 'queued') return -1
  if (status === 'retrieving_reviewed_sources' || status === 'searching_live_sources') return 1
  if (status === 'awaiting_confirmation') return progressSteps.length
  return progressSteps.findIndex((step) => step.status === status)
})

onUnmounted(() => {
  clearSearch()
  planning.stopPolling()
})

onMounted(async () => {
  try {
    loadSettingsIntoForm(await getMySettings())
  } catch {
    // Settings defaults are optional; the generation service still supplies its defaults.
  }
  if (deepLinkJobId) {
    const restored = await planning.restore(deepLinkJobId)
    if (!restored) {
      deepLinkActive.value = false
      formError.value = planning.message || '无法恢复该行程预览，请重新发起智能规划。'
    }
  }
})
</script>

<template>
  <main class="plan-page" ref="root">
    <header class="plan-header">
      <div class="plan-header__intro">
        <p class="eyebrow">TRAVEL PLANNING DESK</p>
        <h1>从一处目的地开始安排。</h1>
        <p>选好边界，再决定自己慢慢排，还是让智能规划先整理一版。</p>
      </div>
      <div class="head-signal"><MapPinned :size="18" /><span>旅行规划桌面</span></div>
    </header>

    <section v-if="!deepLinkActive" class="planning-desk" aria-labelledby="planning-title" data-reveal>
      <div class="desk-heading">
        <h2 id="planning-title">这趟旅行要去哪里？</h2>
        <p>目的地、日期与偏好会成为你的行程边界。</p>
      </div>
      <form class="plan-form" @submit.prevent="createSmart">
        <div class="destination-field">
          <label for="destination">目的地</label>
          <div class="combobox-wrap">
            <Search :size="18" aria-hidden="true" />
            <input id="destination" v-model="destinationQuery" role="combobox" aria-autocomplete="list" :aria-controls="'destination-results'" :aria-expanded="destinationOpen" :aria-activedescendant="activeOption >= 0 ? `destination-option-${activeOption}` : undefined" autocomplete="off" placeholder="搜索城市、区县或景区" @input="onDestinationInput" @keydown="onDestinationKeydown" @focus="destinationQuery.trim() && (destinationOpen = true)">
          </div>
          <Transition name="fade">
            <p v-if="selectedDestination" class="selected-destination"><Check :size="15" />已选择：{{ selectedDestination.name }} <span>{{ selectedDestination.display_address }}</span></p>
          </Transition>
          <Transition name="fade">
            <ul v-if="destinationOpen" id="destination-results" class="destination-results" role="listbox" aria-label="目的地搜索结果">
              <li v-if="destinationLoading" class="search-state"><LoaderCircle class="spin" :size="16" />正在搜索目的地</li>
              <li v-else-if="!destinationResults.length" class="search-state">没有找到匹配目的地，请换个关键词。</li>
              <li v-for="(destination, index) in destinationResults" :id="`destination-option-${index}`" :key="destination.id" role="option" :aria-selected="index === activeOption" :class="{ active: index === activeOption }" @mousedown.prevent="selectDestination(destination)" @mousemove="activeOption = index"><strong>{{ destination.name }}</strong><span>{{ destination.display_address }}</span></li>
            </ul>
          </Transition>
        </div>

        <div class="date-row">
          <label>开始日期<input v-model="startDate" :min="today" type="date"></label>
          <label>结束日期<input v-model="endDate" :min="startDate || today" type="date"></label>
        </div>
        <p class="duration" aria-live="polite">{{ duration }}<span v-if="selectedDestination"> · {{ selectedDestination.name }}</span></p>

        <fieldset>
          <legend>旅行偏好 <span>最多 3 个</span></legend>
          <p v-if="savedSettings" class="preference-default">默认使用个人设置，可在本次行程中调整。</p>
          <div class="tag-list">
            <button v-for="tag in preferences" :key="tag" type="button" :data-tag="tag" :aria-pressed="selectedTags.includes(tag)" :class="{ selected: selectedTags.includes(tag) }" @click="toggleTag(tag)">{{ tag }}</button>
          </div>
          <button v-if="selectedTags.length" class="clear-preference" type="button" @click="clearTags">清除本次偏好</button>
        </fieldset>
        <fieldset>
          <legend>旅行节奏</legend>
          <div class="choice-list">
            <button type="button" :class="{ selected: selectedPace === 'slow' }" @click="setPace('slow')">慢行</button>
            <button type="button" :class="{ selected: selectedPace === 'balanced' }" @click="setPace('balanced')">适中</button>
            <button type="button" :class="{ selected: selectedPace === 'fast' }" @click="setPace('fast')">紧凑</button>
            <button class="clear-preference" type="button" @click="setPace(null)">不设节奏</button>
          </div>
        </fieldset>
        <fieldset>
          <legend>同行方式</legend>
          <div class="choice-list">
            <button type="button" :class="{ selected: selectedTravelerType === 'solo' }" @click="setTravelerType('solo')">独自出行</button>
            <button type="button" :class="{ selected: selectedTravelerType === 'couple' }" @click="setTravelerType('couple')">情侣</button>
            <button type="button" :class="{ selected: selectedTravelerType === 'friends' }" @click="setTravelerType('friends')">朋友</button>
            <button type="button" :class="{ selected: selectedTravelerType === 'family' }" @click="setTravelerType('family')">家庭</button>
            <button class="clear-preference" type="button" @click="setTravelerType(null)">不设同行方式</button>
          </div>
        </fieldset>
        <fieldset class="must-visit-field">
          <legend>必去地点 <span>可选，最多 6 个</span></legend>
          <p>从高德检索结果中选择后，系统会强制将这些地点纳入生成方案。</p>
          <div class="must-visit-search">
            <input v-model="mustVisitQuery" :disabled="!selectedDestination" placeholder="搜索想去的景点，例如：故宫博物院" @keydown.enter.prevent="searchMustVisitPOIs">
            <button type="button" :disabled="!selectedDestination || !mustVisitQuery.trim() || mustVisitLoading" @click="searchMustVisitPOIs"><Search :size="16" />{{ mustVisitLoading ? '搜索中' : '搜索' }}</button>
          </div>
          <ul v-if="mustVisitResults.length" class="must-visit-results" aria-label="地点搜索结果">
            <li v-for="poi in mustVisitResults" :key="poi.id"><span><strong>{{ poi.name }}</strong><small>{{ poi.address }}</small></span><button type="button" :disabled="mustVisitPoi.some((item) => item.id === poi.id)" @click="addMustVisitPOI(poi)"><Plus :size="15" />添加</button></li>
          </ul>
          <ul v-if="mustVisitPoi.length" class="must-visit-selected" aria-label="已选必去地点">
            <li v-for="poi in mustVisitPoi" :key="poi.id"><span>{{ poi.name }}</span><button type="button" :title="`移除${poi.name}`" :aria-label="`移除${poi.name}`" @click="removeMustVisitPOI(poi.id)"><X :size="14" /></button></li>
          </ul>
        </fieldset>
        <label>补充想法 <span class="optional">可选</span><textarea v-model="prompt" rows="4" maxlength="2000" placeholder="例如：有老人同行，想慢一点，晚上想逛夜市。"></textarea></label>
        <Transition name="slide-down">
          <p v-if="formError" class="error" role="alert">{{ formError }}</p>
        </Transition>
        <div class="actions">
          <button class="manual-action" type="button" :disabled="manualCreating" @click="createManual">
            <span>{{ manualCreating ? '正在创建行程' : '手动规划' }}</span>
            <ArrowRight :size="17" :class="{ spin: manualCreating }" />
          </button>
          <button class="smart-action" type="submit" :disabled="planning.isWorking">
            <span>{{ planning.isWorking ? '正在生成预览' : '智能规划' }}</span>
            <Sparkles :size="17" />
          </button>
        </div>
      </form>
    </section>

    <Transition name="fade">
      <section v-if="planning.state !== 'idle'" class="generation-status" aria-live="polite" aria-atomic="true" aria-labelledby="generation-title" data-reveal>
        <div class="generation-head">
          <div>
            <p class="phase-label">AI PLANNING</p>
            <h2 id="generation-title">{{ generationTitle }}</h2>
            <p>{{ planning.message || '系统只会将已核验的地点和资料放入预览。' }}</p>
          </div>
          <button v-if="planning.canRetry" class="retry" type="button" :disabled="planning.isWorking" @click="planning.retry">
            <span>重新生成</span><RefreshCw :size="16" :class="{ spin: planning.isWorking }" />
          </button>
        </div>
        <div v-if="planning.isWorking" class="progress" role="progressbar" :aria-valuenow="planning.progress" aria-valuemin="0" aria-valuemax="100">
          <div class="progress-summary">
            <span>{{ generationStage }}</span>
            <strong>{{ planning.progress }}%</strong>
          </div>
          <span class="progress-track">
            <i :style="{ transform: `scaleX(${planning.progress / 100})` }"></i>
          </span>
          <ol class="progress-steps">
            <li v-for="(step, index) in progressSteps" :key="step.status" :class="{ active: index === currentProgressStep, complete: index < currentProgressStep }">
              <span>{{ index < currentProgressStep ? '✓' : index + 1 }}</span>
              <small>{{ step.label }}</small>
            </li>
          </ol>
        </div>
        <div v-if="planning.state === 'ready' && planning.preview" class="preview">
          <div class="preview-title">
            <div>
              <strong>{{ planning.preview.draft.title }}</strong>
              <p>确认后将立即进入路线规划页面。</p>
            </div>
            <span>{{ planning.preview.draft.days.length }} 天</span>
          </div>
          <div class="preview-days">
            <article v-for="day in planning.preview.draft.days" :key="day.date">
              <time>{{ day.date }}</time>
              <ol>
                <li v-for="activity in day.activities" :key="`${day.date}-${activity.poi_id}`">
                  <strong>{{ activity.poi_name }}</strong>
                  <span>{{ activity.title }}</span>
                </li>
              </ol>
            </article>
          </div>
          <div class="citations">
            <strong>参考资料 {{ planning.preview.citations.length }}</strong>
            <ul>
              <li v-for="citation in planning.preview.citations" :key="citation.chunk_id">
                <b>{{ citationLabel(citation.source_type) }}</b>
                <span>{{ citation.content }}</span>
              </li>
            </ul>
          </div>
          <button class="smart-action" type="button" :disabled="planning.applyingPreview" @click="confirmPreview">
            <span>{{ planning.applyingPreview ? '正在写入行程' : '确认并进入路线规划' }}</span>
            <Check :size="17" />
          </button>
        </div>
        <p v-else-if="planning.state === 'ready' && planning.previewLoading" class="outcome">
          <LoaderCircle class="spin" :size="17" />正在读取可确认的行程预览。
        </p>
        <p v-else-if="planning.state === 'no_result' || planning.state === 'clarification' || planning.state === 'unavailable'" class="outcome">
          <SearchX v-if="planning.state === 'no_result'" :size="17" />
          <CircleAlert v-else :size="17" />{{ planning.message }}
        </p>
      </section>
    </Transition>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.plan-page {
  background: var(--field-paper);
  color: var(--field-ink);
  min-height: calc(100vh - 70px);
  padding: 48px clamp(20px, 6vw, 96px) 88px;
}

.plan-header,
.planning-desk,
.generation-status {
  margin: 0 auto;
  max-width: 1040px;
  width: 100%;
}

/* ============ 页头 ============ */
.plan-header {
  align-items: flex-end;
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  display: flex;
  gap: 28px;
  justify-content: space-between;
  padding-bottom: 32px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.plan-header__intro { min-width: 0; }

.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 10px;
  text-transform: uppercase;
}

.plan-header h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(36px, 5vw, 60px);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.08;
  margin: 0;
}

.plan-header p {
  color: var(--field-ink-soft);
  font-size: 15px;
  line-height: 1.65;
  margin: 16px 0 0;
  max-width: 580px;
}

.head-signal {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  display: inline-flex;
  flex: 0 0 auto;
  font: 700 12px var(--field-mono);
  gap: 8px;
  letter-spacing: 0.04em;
  padding: 10px 14px;
}

/* ============ 规划面板 ============ */
.planning-desk {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-soft);
  margin-top: 40px;
  padding: clamp(24px, 4vw, 44px);
}

.desk-heading {
  border-bottom: 1px solid var(--field-line);
  padding-bottom: 18px;
}

.desk-heading h2 {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin: 0;
}

.desk-heading p {
  color: var(--field-ink-soft);
  font-size: 13px;
  line-height: 1.6;
  margin: 8px 0 0;
}

.plan-form {
  display: grid;
  gap: 24px;
  padding-top: 26px;
}

.plan-form label,
.plan-form fieldset {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 13px;
  font-weight: 700;
  gap: 8px;
}

.plan-form input,
.plan-form textarea {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font: inherit;
  min-height: 48px;
  padding: 12px 14px;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.plan-form input:hover,
.plan-form textarea:hover {
  border-color: var(--field-teal);
}

.plan-form input:focus,
.plan-form textarea:focus {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.plan-form input:focus-visible,
.plan-form textarea:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.plan-form textarea {
  resize: vertical;
  line-height: 1.6;
}

/* ============ 目的地下拉 ============ */
.combobox-wrap {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 10px;
  padding: 0 14px;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.combobox-wrap:hover { border-color: var(--field-teal); }

.combobox-wrap:focus-within {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.combobox-wrap svg { color: var(--field-teal); flex: 0 0 auto; }

.combobox-wrap input {
  background: transparent;
  border: 0;
  min-width: 0;
  outline: 0;
  padding-left: 0;
  width: 100%;
}

.combobox-wrap input:focus,
.combobox-wrap input:focus-visible {
  box-shadow: none;
  outline: 0;
}

.destination-field { position: relative; }

.selected-destination {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  display: flex;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 600;
  gap: 6px;
  margin: 0;
  padding: 9px 12px;
}

.selected-destination span {
  color: var(--field-ink-soft);
  font-weight: 500;
}

.destination-results {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  box-shadow: var(--shadow-lift);
  display: grid;
  list-style: none;
  margin: 6px 0 0;
  overflow: hidden;
  padding: 0;
  position: absolute;
  width: 100%;
  z-index: 4;
}

.destination-results li {
  cursor: pointer;
  display: grid;
  gap: 3px;
  padding: 11px 14px;
  transition: background-color var(--motion-fast) var(--ease-standard),
              color var(--motion-fast) var(--ease-standard);
}

.destination-results li + li { border-top: 1px solid var(--field-line); }

.destination-results li.active,
.destination-results li:hover {
  background: var(--field-teal-soft);
  color: var(--field-teal);
}

.destination-results li.active strong,
.destination-results li:hover strong { color: var(--field-teal); }

.destination-results li strong {
  color: var(--field-ink);
  font-size: 14px;
  font-weight: 700;
}

.destination-results li span {
  color: var(--field-muted);
  font-size: 12px;
}

.search-state {
  align-items: center;
  color: var(--field-ink-soft);
  cursor: default;
  display: flex;
  font-size: 13px;
  gap: 8px;
}

.search-state:hover { background: transparent !important; color: var(--field-ink-soft) !important; }

/* ============ 日期 ============ */
.date-row {
  display: grid;
  gap: 16px;
  grid-template-columns: 1fr 1fr;
}

.date-row label { margin: 0; }

.date-row input { min-height: 48px; }

.duration {
  background: var(--field-paper);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  font: 700 13px var(--field-mono);
  letter-spacing: 0.02em;
  margin: 0;
  padding: 10px 14px;
}

.duration span { color: var(--field-ink-soft); font-weight: 500; }

/* ============ 偏好/选择组 ============ */
fieldset {
  border: 0;
  margin: 0;
  padding: 0;
}

legend {
  align-items: baseline;
  color: var(--field-ink);
  display: flex;
  font-size: 14px;
  font-weight: 700;
  gap: 10px;
  margin-bottom: 4px;
}

legend span {
  color: var(--field-muted);
  font: 500 11px var(--field-mono);
  letter-spacing: 0.04em;
}

.preference-default {
  color: var(--field-muted);
  font-size: 12px;
  font-weight: 500;
  margin: 0 0 6px;
}

.tag-list,
.choice-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-list button,
.choice-list button,
.clear-preference {
  background: transparent;
  border: 1px solid var(--field-line);
  border-radius: 999px;
  color: var(--field-ink-soft);
  cursor: pointer;
  font: 700 13px inherit;
  padding: 9px 14px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-fast) var(--ease-standard);
}

.tag-list button:hover,
.choice-list button:hover {
  background: var(--field-teal-soft);
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-1px);
}

.tag-list button:active,
.choice-list button:active { transform: scale(0.97); }

.tag-list button:focus-visible,
.choice-list button:focus-visible,
.clear-preference:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.tag-list button.selected,
.choice-list button.selected {
  background: var(--field-teal);
  border-color: var(--field-teal);
  color: var(--field-white);
}

.tag-list button.selected:hover,
.choice-list button.selected:hover {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
}

.clear-preference {
  border-style: dashed;
  justify-self: start;
}

.clear-preference:hover {
  background: var(--field-paper);
  border-color: var(--field-ink-soft);
  color: var(--field-ink);
}

.must-visit-field > p { color: var(--field-muted); font-size: 12px; font-weight: 500; line-height: 1.55; margin: 0; }
.must-visit-search { display: grid; gap: 8px; grid-template-columns: minmax(0, 1fr) auto; }
.must-visit-search button, .must-visit-results button { align-items: center; background: var(--field-white); border: 1px solid var(--field-teal); border-radius: var(--travel-radius-sm); color: var(--field-teal); cursor: pointer; display: inline-flex; font: 700 12px inherit; gap: 5px; justify-content: center; min-height: 42px; padding: 0 12px; }
.must-visit-search button:disabled, .must-visit-results button:disabled { cursor: not-allowed; opacity: .45; }
.must-visit-results, .must-visit-selected { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; margin: 0; padding: 0; }
.must-visit-results { display: grid; }
.must-visit-results li { align-items: center; border: 1px solid var(--field-line); border-radius: var(--travel-radius-sm); display: flex; gap: 12px; justify-content: space-between; padding: 10px 12px; }
.must-visit-results span { display: grid; gap: 3px; min-width: 0; }
.must-visit-results strong { color: var(--field-ink); font-size: 13px; }
.must-visit-results small { color: var(--field-muted); font-size: 11px; line-height: 1.4; }
.must-visit-selected li { align-items: center; background: var(--field-teal-soft); border: 1px solid #9ad5cf; border-radius: 999px; color: var(--field-teal); display: inline-flex; font-size: 12px; font-weight: 700; gap: 5px; padding: 6px 8px 6px 11px; }
.must-visit-selected button { background: transparent; border: 0; color: inherit; cursor: pointer; display: inline-flex; padding: 2px; }
.must-visit-search button:focus-visible, .must-visit-results button:focus-visible, .must-visit-selected button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }

/* ============ 补充想法 ============ */
.plan-form > label:last-of-type textarea {
  min-height: 110px;
}

.optional {
  color: var(--field-muted);
  font: 500 11px var(--field-mono);
  letter-spacing: 0.04em;
}

/* ============ 错误提示 ============ */
.error {
  align-items: center;
  background: #fff0eb;
  border-left: 3px solid var(--field-coral);
  border-radius: 4px;
  color: #9c4234;
  display: flex;
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
  padding: 11px 14px;
}

/* ============ 操作按钮 ============ */
.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 4px;
}

.manual-action,
.smart-action {
  align-items: center;
  border-radius: var(--travel-radius-sm);
  cursor: pointer;
  display: inline-flex;
  font-size: 14px;
  font-weight: 700;
  gap: 8px;
  justify-content: center;
  min-height: 46px;
  padding: 0 22px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.manual-action {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  color: var(--field-ink);
}

.manual-action:hover:not(:disabled) {
  background: var(--field-paper);
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-2px);
}

.manual-action:active:not(:disabled) { transform: scale(0.98); }

.smart-action {
  background: var(--field-teal);
  border: 1px solid var(--field-teal);
  box-shadow: var(--shadow-soft);
  color: var(--field-white);
}

.smart-action:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  box-shadow: var(--shadow-lift);
  color: var(--field-white);
  transform: translateY(-2px);
}

.smart-action:active:not(:disabled) { transform: scale(0.98); }

.manual-action:focus-visible,
.smart-action:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.manual-action:disabled,
.smart-action:disabled {
  cursor: not-allowed;
  opacity: 0.5;
  transform: none;
}

/* ============ AI 生成状态 ============ */
.generation-status {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-soft);
  display: grid;
  gap: 22px;
  margin-top: 28px;
  padding: clamp(22px, 4vw, 36px);
}

.generation-head {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.generation-head > div { min-width: 0; }

.phase-label {
  color: var(--field-coral);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.generation-head h2 {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 24px;
  font-weight: 600;
  margin: 0;
}

.generation-head > div > p {
  color: var(--field-ink-soft);
  font-size: 13px;
  line-height: 1.6;
  margin: 8px 0 0;
}

.retry {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 700;
  gap: 6px;
  min-height: 38px;
  padding: 0 14px;
  transition: background-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-fast) var(--ease-standard);
}

.retry:hover:not(:disabled) {
  background: var(--field-teal);
  color: var(--field-white);
  transform: translateY(-1px);
}

.retry:active:not(:disabled) { transform: scale(0.97); }

.retry:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.retry:disabled { cursor: not-allowed; opacity: 0.5; }

/* ============ 进度条 ============ */
.progress { background: var(--field-paper); border: 1px solid var(--field-line); border-radius: var(--travel-radius-sm); display: grid; gap: 14px; padding: 16px; }

.progress-summary {
  align-items: center;
  display: flex;
  font-size: 13px;
  justify-content: space-between;
}

.progress-summary span { color: var(--field-ink-soft); }

.progress-summary strong {
  color: var(--field-teal);
  font: 700 14px var(--field-mono);
}

.progress-track {
  background: var(--field-line);
  border-radius: 999px;
  display: block;
  height: 6px;
  overflow: hidden;
  position: relative;
}

.progress-track i {
  background: linear-gradient(90deg, var(--field-teal), #0aa39c);
  display: block;
  height: 100%;
  transform-origin: left;
  transition: transform var(--motion-slow) var(--ease-out);
}

.progress-steps { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); list-style: none; margin: 0; padding: 0; }
.progress-steps li { align-items: center; color: var(--field-muted); display: grid; gap: 5px; justify-items: center; min-width: 0; position: relative; }
.progress-steps li::before { background: var(--field-line); content: ''; height: 1px; left: calc(-50% + 13px); position: absolute; top: 13px; width: calc(100% - 26px); }
.progress-steps li:first-child::before { display: none; }
.progress-steps li span { align-items: center; background: var(--field-white); border: 1px solid var(--field-line); border-radius: 999px; display: flex; font: 700 11px/1 var(--field-mono); height: 26px; justify-content: center; position: relative; width: 26px; z-index: 1; }
.progress-steps li small { font-size: 11px; overflow: hidden; text-align: center; text-overflow: ellipsis; white-space: nowrap; width: 100%; }
.progress-steps li.complete, .progress-steps li.active { color: var(--field-teal); }
.progress-steps li.complete::before { background: var(--field-teal); }
.progress-steps li.complete span { background: var(--field-teal); border-color: var(--field-teal); color: var(--field-white); }
.progress-steps li.active span { border-color: var(--field-teal); box-shadow: 0 0 0 4px var(--field-teal-soft); color: var(--field-teal); }

/* ============ 预览 ============ */
.preview {
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 18px;
  padding-top: 22px;
}

.preview-title {
  align-items: flex-end;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.preview-title > div { min-width: 0; }

.preview-title strong {
  color: var(--field-ink);
  display: block;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 22px;
  font-weight: 600;
}

.preview-title p {
  color: var(--field-ink-soft);
  font-size: 13px;
  line-height: 1.6;
  margin: 6px 0 0;
}

.preview-title > span {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  flex: 0 0 auto;
  font: 700 12px var(--field-mono);
  padding: 6px 12px;
}

.preview-days {
  display: grid;
  gap: 14px;
}

.preview-days article {
  background: var(--field-paper);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: grid;
  gap: 10px;
  padding: 16px;
}

.preview-days time {
  color: var(--field-teal);
  font: 700 12px var(--field-mono);
  letter-spacing: 0.04em;
}

.preview-days ol {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.preview-days li {
  display: grid;
  gap: 2px;
}

.preview-days li strong {
  color: var(--field-ink);
  font-size: 13px;
  font-weight: 700;
}

.preview-days li span {
  color: var(--field-ink-soft);
  font-size: 12px;
  line-height: 1.5;
}

.citations {
  background: var(--field-paper);
  border-left: 3px solid var(--field-saffron);
  border-radius: 4px;
  display: grid;
  gap: 10px;
  padding: 14px 16px;
}

.citations > strong {
  color: var(--field-ink-soft);
  font: 700 12px var(--field-mono);
  letter-spacing: 0.04em;
}

.citations ul {
  display: grid;
  gap: 10px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.citations li {
  display: grid;
  gap: 3px;
}

.citations li b {
  color: var(--field-saffron);
  font: 700 11px var(--field-mono);
  letter-spacing: 0.04em;
}

.citations li span {
  color: var(--field-ink-soft);
  font-size: 12px;
  line-height: 1.55;
}

.outcome {
  align-items: center;
  background: var(--field-paper);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  display: flex;
  font-size: 14px;
  gap: 8px;
  line-height: 1.6;
  margin: 0;
  padding: 14px 16px;
}

/* ============ 响应式 ============ */
@media (max-width: 720px) {
  .plan-page { padding: 32px 16px 64px; }
  .plan-header { align-items: stretch; flex-direction: column; gap: 18px; }
  .plan-header h1 { font-size: 34px; }
  .date-row { grid-template-columns: 1fr; }
  .must-visit-search { grid-template-columns: 1fr; }
  .actions { flex-direction: column; }
  .manual-action,
  .smart-action { width: 100%; }
  .generation-head { flex-direction: column; }
  .retry { width: 100%; justify-content: center; }
  .preview-title { flex-direction: column; align-items: flex-start; }
}

/* ============ 减少动效 ============ */
@media (prefers-reduced-motion: reduce) {
  .plan-header,
  .plan-form input,
  .plan-form textarea,
  .combobox-wrap,
  .destination-results li,
  .tag-list button,
  .choice-list button,
  .clear-preference,
  .manual-action,
  .smart-action,
  .retry,
  .progress-track i {
    animation: none !important;
    transition: none !important;
  }
  .manual-action:hover:not(:disabled),
  .smart-action:hover:not(:disabled),
  .retry:hover:not(:disabled),
  .tag-list button:hover,
  .choice-list button:hover {
    transform: none !important;
  }
}
</style>
