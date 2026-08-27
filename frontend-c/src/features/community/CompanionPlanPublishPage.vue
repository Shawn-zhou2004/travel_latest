<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowLeft, Check, LoaderCircle, Search, Send } from 'lucide-vue-next'
import CompanionPlanTimeline from './components/CompanionPlanTimeline.vue'
import { canPublishPlan, companionInterestTagLabel, companionInterestTags, inferredCompanionCityCode, publishCompanionPlan, publishPayload, requiresDestinationSelection, type CompanionPace } from './companionPlansApi'
import { getItinerary, type ItineraryDetail } from '@/features/itineraries/api'
import { searchDestinations, type DestinationOption } from '@/features/itineraries/destinationsApi'
import { normalizeApiError } from '@/services/api'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ itineraryId: string }>()
const router = useRouter()
const itinerary = ref<ItineraryDetail>()
const partySize = ref(3)
const budgetMin = ref<number | null>(null)
const budgetMax = ref<number | null>(null)
const currency = ref('CNY')
const pace = ref<CompanionPace>('balanced')
const tags = ref<string[]>(['citywalk'])
const intro = ref('')
const state = ref<'loading' | 'ready' | 'error'>('loading')
const submitting = ref(false)
const error = ref('')
const destinationQuery = ref('')
const selectedDestination = ref<DestinationOption | null>(null)
const destinationResults = ref<DestinationOption[]>([])
const destinationOpen = ref(false)
const destinationLoading = ref(false)
const destinationError = ref('')
const activeOption = ref(-1)
const root = ref<HTMLElement | null>(null)
useReveal(root)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchSequence = 0
const inferredCityCode = computed(() => inferredCompanionCityCode(itinerary.value?.snapshot))
const needsDestinationSelection = computed(() => requiresDestinationSelection(itinerary.value?.snapshot))
const inferredDestinationLabel = computed(() => (itinerary.value?.snapshot as { destination?: { name?: string } } | undefined)?.destination?.name || '行程已识别目的地')
const invalid = computed(() => !canPublishPlan({ partySize: partySize.value, pace: pace.value, tags: tags.value, intro: intro.value }) || (budgetMin.value === null) !== (budgetMax.value === null) || (needsDestinationSelection.value && !selectedDestination.value))

function toggleTag(tag: string) { tags.value = tags.value.includes(tag) ? tags.value.filter((item) => item !== tag) : tags.value.length < 8 ? [...tags.value, tag] : tags.value }
function clearDestinationSearch() {
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  searchTimer = undefined
  searchSequence += 1
  destinationLoading.value = false
}
function onDestinationInput() {
  destinationError.value = ''
  if (selectedDestination.value?.name !== destinationQuery.value) selectedDestination.value = null
  clearDestinationSearch()
  const query = destinationQuery.value.trim()
  if (!query) { destinationResults.value = []; destinationOpen.value = false; activeOption.value = -1; return }
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
      destinationError.value = normalizeApiError(cause).message
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
  destinationError.value = ''
}
function onDestinationKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' && destinationResults.value.length) { event.preventDefault(); destinationOpen.value = true; activeOption.value = (activeOption.value + 1 + destinationResults.value.length) % destinationResults.value.length }
  else if (event.key === 'ArrowUp' && destinationResults.value.length) { event.preventDefault(); destinationOpen.value = true; activeOption.value = (activeOption.value - 1 + destinationResults.value.length) % destinationResults.value.length }
  else if (event.key === 'Enter' && destinationOpen.value && activeOption.value >= 0) { event.preventDefault(); selectDestination(destinationResults.value[activeOption.value]) }
  else if (event.key === 'Escape') destinationOpen.value = false
}
async function load() {
  state.value = 'loading'; error.value = ''
  try { itinerary.value = await getItinerary(props.itineraryId); state.value = 'ready' }
  catch (reason) { state.value = 'error'; error.value = normalizeApiError(reason).message || '这份行程暂时无法用于发布同行计划。' }
}
async function submit() {
  if (submitting.value || invalid.value) return
  submitting.value = true; error.value = ''
  try {
    const form = { party_size: partySize.value, budget_min: budgetMin.value, budget_max: budgetMax.value, currency: budgetMin.value === null ? null : currency.value, travel_pace: pace.value, interest_tags: tags.value, intro_text: intro.value.trim() }
    const plan = await publishCompanionPlan(props.itineraryId, publishPayload(form, needsDestinationSelection.value ? selectedDestination.value : null, inferredCityCode.value))
    await router.push(`/companions/${plan.id}`)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '同行计划暂未提交，请检查路线与信息。' }
  finally { submitting.value = false }
}
onMounted(() => void load())
onUnmounted(clearDestinationSearch)
</script>

<template>
  <main class="publish-page" ref="root">
    <header class="page-header" data-reveal><RouterLink class="back" :to="`/itineraries/${itineraryId}`"><ArrowLeft :size="16" />返回行程</RouterLink><div><p>FIELD / TRAVEL · COMPANION PLAN</p><h1>发起同行计划</h1></div></header>
    <section v-if="state === 'loading'" class="state"><LoaderCircle :size="22" />正在读取可编辑路线。</section>
    <section v-else-if="state === 'error'" class="state error"><p>{{ error }}</p><button type="button" @click="load">重新读取</button></section>
    <form v-else class="publish-grid" @submit.prevent="submit">
      <section class="form-column" data-reveal>
        <section class="route-fact"><p>ROUTE LOCKED FOR REVIEW</p><h2>{{ itinerary?.title }}</h2><span>{{ itinerary?.start_date }} 至 {{ itinerary?.end_date }} · 当前版本 {{ itinerary?.version }}</span></section>
        <section v-if="inferredCityCode" class="destination-readonly"><p>目的地城市</p><strong>{{ inferredDestinationLabel }}</strong></section>
        <section v-else class="destination-field"><label for="companion-destination">目的地城市</label><div class="combobox-wrap"><Search :size="17" aria-hidden="true" /><input id="companion-destination" v-model="destinationQuery" role="combobox" aria-autocomplete="list" aria-controls="companion-destination-results" :aria-expanded="destinationOpen" :aria-activedescendant="activeOption >= 0 ? `companion-destination-option-${activeOption}` : undefined" autocomplete="off" placeholder="搜索城市、区县或景区" @input="onDestinationInput" @keydown="onDestinationKeydown" @focus="destinationQuery.trim() && (destinationOpen = true)"></div><p v-if="selectedDestination" class="selected-destination"><Check :size="15" />已选择：{{ selectedDestination.name }} <span>{{ selectedDestination.display_address }}</span></p><p v-if="destinationError" class="destination-status error-message" role="alert">{{ destinationError }}</p><p v-else-if="destinationLoading" class="destination-status" role="status" aria-live="polite"><LoaderCircle class="spin" :size="15" />正在搜索目的地城市</p><p v-else-if="destinationOpen && !destinationResults.length" class="destination-status" role="status" aria-live="polite">没有找到匹配目的地，请换个关键词。</p><ul v-if="destinationOpen && destinationResults.length" id="companion-destination-results" class="destination-results" role="listbox" aria-label="目的地城市搜索结果"><li v-for="(destination, index) in destinationResults" :id="`companion-destination-option-${index}`" :key="destination.id" role="option" :aria-selected="index === activeOption" :class="{ active: index === activeOption }" @mousedown.prevent="selectDestination(destination)" @mousemove="activeOption = index"><strong>{{ destination.name }}</strong><span>{{ destination.display_address }}</span></li></ul><Transition name="fade"><p v-if="needsDestinationSelection && !selectedDestination" class="validation" role="alert">请选择同行计划的目的地城市。</p></Transition></section>
        <label>同行人数<input v-model.number="partySize" type="number" min="2" max="12"><small>包含你本人，最多 12 人。</small></label>
        <div class="budget"><label>预算下限<input v-model.number="budgetMin" type="number" min="0" placeholder="可选"></label><label>预算上限<input v-model.number="budgetMax" type="number" min="0" placeholder="可选"></label><label>币种<select v-model="currency" :disabled="budgetMin === null && budgetMax === null"><option value="CNY">CNY</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label></div>
        <fieldset><legend>旅行节奏</legend><label v-for="item in ([['slow', '从容'], ['balanced', '均衡'], ['packed', '紧凑']] as const)" :key="item[0]"><input v-model="pace" type="radio" :value="item[0]">{{ item[1] }}</label></fieldset>
        <fieldset><legend>同行兴趣</legend><label v-for="tag in companionInterestTags" :key="tag"><input type="checkbox" :checked="tags.includes(tag)" @change="toggleTag(tag)">{{ companionInterestTagLabel(tag) }}</label></fieldset>
        <label>同行说明<textarea v-model="intro" rows="6" maxlength="2000" placeholder="说说你的旅行节奏、期待和协作方式。"></textarea></label>
        <p class="privacy"><Check :size="16" />路线顺序会在成员加入后继续协作编辑；联系方式与具体集合信息保持私密。</p>
        <Transition name="fade"><p v-if="error" class="error-message" role="alert">{{ error }}</p></Transition><button class="submit" type="submit" :disabled="invalid || submitting"><Send :size="16" />{{ submitting ? '正在提交' : '提交同行计划审核' }}</button>
      </section>
      <aside class="preview" data-reveal><header><p>READ-ONLY ROUTE</p><h2>路线预览</h2></header><CompanionPlanTimeline :route-count="itinerary?.snapshot.days.reduce((count, day) => count + day.events.length, 0) ?? 0" :itinerary="itinerary?.snapshot" /></aside>
    </form>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.publish-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1200px;
  min-height: calc(100vh - 70px);
  padding: 34px 22px 68px;
}

/* ============ 页头 ============ */
.page-header {
  align-items: end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  gap: 28px;
  padding-bottom: 22px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.back {
  align-items: center;
  color: var(--field-teal);
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 6px;
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.back:hover { color: var(--field-deep); transform: translateX(-2px); }
.back:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

.page-header p, .route-fact p, .preview p {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .09em;
  margin: 0 0 8px;
}

.page-header h1 { font-size: 36px; letter-spacing: 0; margin: 0; }

/* ============ 状态条 ============ */
.state {
  align-items: center;
  color: var(--field-muted);
  display: flex;
  gap: 9px;
  justify-content: center;
  min-height: 260px;
}

.state.error { flex-direction: column; color: var(--field-coral); }

.state button {
  background: var(--field-deep);
  border: 0;
  color: #fff;
  cursor: pointer;
  font-weight: 800;
  padding: 11px 14px;
  transition: background-color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.state button:hover:not(:disabled) { background: var(--field-teal); transform: translateY(-1px); }
.state button:active:not(:disabled) { transform: scale(0.98); }
.state button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }

/* ============ 布局栅格 ============ */
.publish-grid {
  align-items: start;
  display: grid;
  gap: 54px;
  grid-template-columns: minmax(0, .9fr) minmax(350px, 1.1fr);
  padding-top: 31px;
}

.form-column { display: grid; gap: 19px; }

/* ============ 路线信息 ============ */
.route-fact {
  border-left: 3px solid var(--field-coral);
  display: grid;
  gap: 5px;
  padding-left: 15px;
}

.route-fact h2, .preview h2 { font-size: 22px; margin: 0; }
.route-fact span, .privacy { color: var(--field-muted); font-size: 12px; line-height: 1.55; }

/* ============ 表单控件 ============ */
.form-column > label, .budget label {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 12px;
  font-weight: 800;
  gap: 7px;
}

.form-column input, .form-column select, .form-column textarea {
  background: #fff;
  border: 1px solid var(--field-line);
  color: var(--field-ink);
  font: inherit;
  min-height: 42px;
  padding: 9px;
  transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.form-column input:focus-visible, .form-column select:focus-visible, .form-column textarea:focus-visible {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.form-column textarea { line-height: 1.55; resize: vertical; }
.form-column small { color: var(--field-muted); font-weight: 500; }

.budget { display: grid; gap: 10px; grid-template-columns: 1fr 1fr 90px; }

fieldset {
  border: 0;
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 0;
}

legend { color: var(--field-ink-soft); font-size: 12px; font-weight: 800; padding: 0 8px 0 0; }
fieldset label { align-items: center; display: flex; font-size: 12px; gap: 5px; }
fieldset input { accent-color: var(--field-teal); min-height: auto !important; padding: 0 !important; }

.privacy {
  align-items: flex-start;
  background: var(--travel-sky);
  display: flex;
  gap: 8px;
  margin: 0;
  padding: 12px;
}

.privacy svg { color: var(--field-teal); flex: 0 0 auto; }

/* ============ 提交按钮 ============ */
.submit {
  align-items: center;
  background: var(--field-deep);
  border: 0;
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  gap: 7px;
  justify-content: center;
  min-height: 43px;
  padding: 11px 14px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.submit:hover:not(:disabled) { background: var(--field-teal); transform: translateY(-1px); box-shadow: var(--shadow-soft); }
.submit:active:not(:disabled) { transform: translateY(0) scale(0.98); }
.submit:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.submit:disabled { cursor: not-allowed; opacity: .5; }

.error-message { color: var(--field-coral); font-size: 12px; margin: 0; }

/* ============ 预览列 ============ */
.preview { border-top: 2px solid var(--field-ink); display: grid; gap: 18px; padding-top: 15px; }

/* ============ 目的地只读 ============ */
.destination-readonly {
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 5px;
  padding: 14px 0;
}

.destination-readonly p { color: var(--field-ink-soft); font-size: 12px; font-weight: 800; margin: 0; }
.destination-readonly strong { font-size: 15px; }

/* ============ 目的地搜索 ============ */
.destination-field { position: relative; }
.destination-field > label { color: var(--field-ink-soft); display: grid; font-size: 12px; font-weight: 800; gap: 7px; }

.combobox-wrap {
  align-items: center;
  background: #fff;
  border: 1px solid var(--field-line);
  display: flex;
  gap: 8px;
  min-height: 42px;
  padding: 0 10px;
  transition: border-color var(--motion-fast) var(--ease-standard);
}

.combobox-wrap svg { color: var(--field-teal); flex: 0 0 auto; }
.combobox-wrap input { border: 0; min-width: 0; outline: 0; padding: 0; width: 100%; }
.combobox-wrap:focus-within { border-color: var(--field-teal); outline: 2px solid var(--field-teal-soft); outline-offset: 2px; }

.destination-results {
  background: #fff;
  border: 1px solid var(--field-line);
  display: grid;
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  position: absolute;
  width: 100%;
  z-index: 2;
}

.destination-results li { cursor: pointer; display: grid; gap: 3px; padding: 10px; transition: background-color var(--motion-fast) var(--ease-standard); }
.destination-results li + li { border-top: 1px solid var(--field-line); }
.destination-results li.active, .destination-results li:hover { background: var(--field-teal-soft); }
.destination-results strong { font-size: 13px; }

.destination-results span, .selected-destination span, .destination-status { color: var(--field-muted); font-size: 12px; }

.selected-destination, .destination-status { align-items: center; display: flex; gap: 6px; margin: 0; }
.selected-destination svg, .destination-status svg { color: var(--field-teal); }

.validation, .error-message { color: var(--field-coral); font-size: 12px; font-weight: 700; margin: 0; }

.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ============ 响应式 ============ */
@media (max-width: 760px) {
  .publish-page { padding: 22px 15px 42px; }
  .page-header { align-items: start; flex-direction: column; gap: 17px; }
  .publish-grid { grid-template-columns: 1fr; }
  .preview { grid-row: 1; }
  .budget { grid-template-columns: 1fr 1fr; }
  .budget label:last-child { grid-column: 1 / -1; }
}

@media (prefers-reduced-motion: reduce) {
  .page-header { animation: none; }
  .state svg { animation: none; }
  .spin { animation: none; }
  .back, .state button, .submit,
  .form-column input, .form-column select, .form-column textarea,
  .combobox-wrap, .destination-results li { transition: none; }
}
</style>
