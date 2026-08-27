<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { LoaderCircle, RefreshCw, Search, SlidersHorizontal } from 'lucide-vue-next'
import CompanionPlanCard from './components/CompanionPlanCard.vue'
import { companionInterestTagLabel, companionInterestTags, listCompanionPlans, type CompanionPace, type CompanionPlanSummary, type CompanionTripKind } from './companionPlansApi'
import { searchDestinations, type DestinationOption } from '@/features/itineraries/destinationsApi'
import { useReveal } from '@/composables/useReveal'

const plans = ref<CompanionPlanSummary[]>([])
const cityQuery = ref('')
const selectedCity = ref<DestinationOption | null>(null)
const cityResults = ref<DestinationOption[]>([])
const cityOpen = ref(false)
const cityLoading = ref(false)
const cityActive = ref(-1)
const startDate = ref('')
const endDate = ref('')
const tripKind = ref<CompanionTripKind | ''>('')
const pace = ref<CompanionPace | ''>('')
const tag = ref('')
const seatsOnly = ref(false)
const loading = ref(true)
const error = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchSequence = 0

async function loadPlans() {
  loading.value = true
  error.value = ''
  try {
    const page = await listCompanionPlans({ city_code: selectedCity.value?.city_code || undefined, start_date: startDate.value || undefined, end_date: endDate.value || undefined, trip_kind: tripKind.value || undefined, travel_pace: pace.value || undefined, tags: tag.value ? [tag.value] : undefined, has_slots: seatsOnly.value || undefined })
    plans.value = page.items
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '同行计划暂时无法读取。'
  } finally {
    loading.value = false
  }
}

function clearCitySearch() {
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  searchTimer = undefined
  searchSequence += 1
  cityLoading.value = false
}

function onCityInput() {
  if (selectedCity.value?.name !== cityQuery.value) selectedCity.value = null
  clearCitySearch()
  const query = cityQuery.value.trim()
  if (!query) { cityResults.value = []; cityOpen.value = false; cityActive.value = -1; return }
  cityOpen.value = true
  cityResults.value = []
  const request = searchSequence
  searchTimer = setTimeout(async () => {
    cityLoading.value = true
    try {
      const results = await searchDestinations(query)
      if (request !== searchSequence) return
      cityResults.value = results
      cityActive.value = results.length ? 0 : -1
    } catch {
      if (request !== searchSequence) return
      cityResults.value = []
    } finally {
      if (request === searchSequence) cityLoading.value = false
    }
  }, 250)
}

function selectCity(destination: DestinationOption) {
  selectedCity.value = destination
  cityQuery.value = destination.name
  cityResults.value = []
  cityOpen.value = false
  cityActive.value = -1
}

function onCityKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' && cityResults.value.length) { event.preventDefault(); cityOpen.value = true; cityActive.value = (cityActive.value + 1 + cityResults.value.length) % cityResults.value.length }
  else if (event.key === 'ArrowUp' && cityResults.value.length) { event.preventDefault(); cityOpen.value = true; cityActive.value = (cityActive.value - 1 + cityResults.value.length) % cityResults.value.length }
  else if (event.key === 'Enter' && cityOpen.value && cityActive.value >= 0) { event.preventDefault(); selectCity(cityResults.value[cityActive.value]) }
  else if (event.key === 'Escape') cityOpen.value = false
}

function closeCityResultsAfterBlur() {
  window.setTimeout(() => { cityOpen.value = false }, 150)
}

function resetFilters() {
  cityQuery.value = ''
  selectedCity.value = null
  cityResults.value = []
  cityOpen.value = false
  startDate.value = ''
  endDate.value = ''
  tripKind.value = ''
  pace.value = ''
  tag.value = ''
  seatsOnly.value = false
  void loadPlans()
}

onMounted(loadPlans)
onUnmounted(clearCitySearch)
</script>

<template>
  <main class="discovery-page" aria-label="同行计划发现" ref="root">
    <header class="departure-heading" data-reveal>
      <div><p class="section-label">FIELD / TRAVEL · DEPARTURE WINDOW</p><h1>同行计划</h1><p>从公开路线开始，找到适合一起出发的人。</p></div>
      <div class="departure-stamp"><span>OPEN ROUTES</span><strong>FIND<br />A PACE</strong><small>同行计划 / 01</small></div>
    </header>

    <form class="filters" data-reveal @submit.prevent="loadPlans">
      <div class="destination">
        <Search :size="17" />
        <input v-model="cityQuery" role="combobox" aria-autocomplete="list" aria-controls="companion-city-results" :aria-expanded="cityOpen" :aria-activedescendant="cityActive >= 0 ? `companion-city-option-${cityActive}` : undefined" autocomplete="off" placeholder="搜索目的地城市" @input="onCityInput" @keydown="onCityKeydown" @focus="cityQuery.trim() && (cityOpen = true)" @blur="closeCityResultsAfterBlur">
        <LoaderCircle v-if="cityLoading" :size="14" class="spin" aria-hidden="true" />
        <ul v-if="cityOpen && cityResults.length" id="companion-city-results" class="city-results" role="listbox" aria-label="目的地城市搜索结果"><li v-for="(destination, index) in cityResults" :id="`companion-city-option-${index}`" :key="destination.id" role="option" :aria-selected="index === cityActive" :class="{ active: index === cityActive }" @mousedown.prevent="selectCity(destination)" @mousemove="cityActive = index"><strong>{{ destination.name }}</strong><span>{{ destination.display_address }}</span></li></ul>
      </div>
      <label><span>起始日期</span><input v-model="startDate" type="date" /></label>
      <label><span>结束日期</span><input v-model="endDate" type="date" /></label>
      <select v-model="tripKind" aria-label="计划类型"><option value="">全部类型</option><option value="trip">同行路线</option><option value="activity">短途活动</option></select>
      <select v-model="pace" aria-label="出行节奏"><option value="">全部节奏</option><option value="slow">慢行</option><option value="balanced">均衡</option><option value="packed">紧凑</option></select>
      <select v-model="tag" aria-label="兴趣标签"><option value="">全部兴趣</option><option v-for="interestTag in companionInterestTags" :key="interestTag" :value="interestTag">{{ companionInterestTagLabel(interestTag) }}</option></select>
      <label class="slots"><input v-model="seatsOnly" type="checkbox" />仅看有名额</label>
      <button type="submit"><SlidersHorizontal :size="16" />筛选</button>
    </form>

    <section v-if="loading" class="skeletons" aria-live="polite"><span>正在整理出发窗口</span><div v-for="index in 3" :key="index" class="skeleton" /></section>
    <section v-else-if="error" class="state-panel" role="alert"><p>计划读取失败</p><strong>{{ error }}</strong><button type="button" @click="loadPlans"><RefreshCw :size="16" />重试</button></section>
    <section v-else-if="!plans.length" class="state-panel"><p>没有匹配的同行计划</p><strong>放宽日期或目的地条件，看看新的出发窗口。</strong><button type="button" @click="resetFilters">重置筛选</button></section>
    <section v-else class="plan-list" aria-label="公开同行计划" data-reveal><CompanionPlanCard :plan="plans[0]" featured :index="0" /><div v-if="plans.length > 1" class="section-rule"><span>MORE DEPARTURES</span></div><CompanionPlanCard v-for="(plan, index) in plans.slice(1)" :key="plan.id" :plan="plan" :index="index + 1" /></section>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.discovery-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1180px;
  padding: 58px 28px 88px;
}

/* ============ 页头 ============ */
.departure-heading {
  align-items: end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  justify-content: space-between;
  padding-bottom: 31px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.section-label {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: .14em;
  margin: 0;
}

.departure-heading h1 {
  font-size: clamp(48px, 7vw, 80px);
  line-height: 1;
  margin: 14px 0;
}

.departure-heading > div > p:last-child {
  color: var(--field-ink-soft);
  margin: 0;
}

.departure-stamp {
  border: 1px solid var(--field-teal);
  color: var(--field-teal);
  display: grid;
  font: 800 10px var(--field-mono);
  gap: 5px;
  letter-spacing: .08em;
  min-width: 134px;
  padding: 10px;
  transform: rotate(2deg);
  transition: transform var(--motion-base) var(--ease-out);
}

.departure-stamp span { color: var(--field-coral); }
.departure-stamp strong { font-size: 15px; line-height: 1.05; }
.departure-stamp small { color: var(--field-muted); font-size: 8px; }

/* ============ 筛选区 ============ */
.filters {
  border-bottom: 1px solid var(--field-line);
  display: grid;
  gap: 9px;
  grid-template-columns: minmax(160px, 1.4fr) repeat(2, minmax(130px, 1fr)) repeat(3, minmax(110px, .8fr)) auto auto;
  padding: 17px 0;
}

.filters label, .filters select {
  background: transparent;
  border: 1px solid var(--field-line);
  color: var(--field-ink-soft);
  font: 700 11px var(--field-mono);
  min-width: 0;
  transition: border-color var(--motion-fast) var(--ease-standard), background-color var(--motion-fast) var(--ease-standard);
}

.filters label:not(.slots) {
  display: grid;
  gap: 2px;
  padding: 6px 10px;
}

.filters label span { color: var(--field-muted); font-size: 9px; }

.filters input, .filters select {
  background: transparent;
  border: 0;
  color: var(--field-ink);
  font: inherit;
  min-width: 0;
  outline: 0;
}

.filters select { border: 1px solid var(--field-line); padding: 0 8px; }

.filters label:hover:not(.slots) {
  border-color: color-mix(in srgb, var(--field-teal) 50%, var(--field-line));
}

.filters input:focus-visible, .filters select:focus-visible {
  outline: 2px solid var(--field-teal-soft);
  outline-offset: 2px;
}

.filters .destination {
  align-items: center;
  display: flex;
  gap: 8px;
  padding: 0 10px;
  position: relative;
}

.destination svg { color: var(--field-teal); flex: 0 0 auto; }
.destination input { min-width: 0; }

.city-results {
  background: #fff;
  border: 1px solid var(--field-line);
  box-shadow: var(--shadow-soft);
  display: grid;
  gap: 3px;
  left: 0;
  list-style: none;
  margin: 4px 0 0;
  max-height: 280px;
  overflow-y: auto;
  padding: 0;
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 5;
}

.city-results li { cursor: pointer; display: grid; gap: 3px; padding: 10px; transition: background-color var(--motion-fast) var(--ease-standard); }
.city-results li + li { border-top: 1px solid var(--field-line); }
.city-results li.active, .city-results li:hover { background: var(--field-teal-soft); }
.city-results strong { color: var(--field-ink); font-size: 13px; }
.city-results span { color: var(--field-muted); font-size: 11px; }

.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.slots {
  align-items: center;
  display: flex;
  gap: 6px;
  padding: 0 9px;
  white-space: nowrap;
}

.slots input { accent-color: var(--field-teal); }

.filters button, .state-panel button {
  align-items: center;
  background: var(--field-ink);
  border: 1px solid var(--field-ink);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font: 800 11px var(--field-mono);
  gap: 7px;
  justify-content: center;
  padding: 0 13px;
  transition: background-color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.filters button:hover:not(:disabled), .state-panel button:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  transform: translateY(-1px);
  box-shadow: var(--shadow-soft);
}

.filters button:active:not(:disabled), .state-panel button:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.filters button:focus-visible, .state-panel button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.filters button:disabled, .state-panel button:disabled {
  cursor: not-allowed;
  opacity: .5;
}

/* ============ 骨架屏 ============ */
.skeletons { display: grid; gap: 14px; margin-top: 28px; }
.skeletons > span { color: var(--field-muted); font: 700 11px var(--field-mono); }
.skeleton {
  animation: pulse 1.3s ease-in-out infinite;
  background: var(--field-teal-soft);
  height: 142px;
}

/* ============ 状态面板 ============ */
.state-panel {
  border: 1px solid var(--field-line);
  display: grid;
  gap: 9px;
  justify-items: start;
  margin-top: 30px;
  padding: 25px;
}

.state-panel p { color: var(--field-coral); font: 800 11px var(--field-mono); margin: 0; }
.state-panel strong { color: var(--field-ink-soft); font-size: 14px; font-weight: 500; }
.state-panel button { min-height: 37px; margin-top: 8px; }

/* ============ 计划列表 ============ */
.plan-list { margin-top: 27px; }

.section-rule {
  border-top: 1px solid var(--field-line);
  color: var(--field-muted);
  font: 800 10px var(--field-mono);
  letter-spacing: .11em;
  margin-top: 12px;
  padding-top: 16px;
}

@keyframes pulse { 50% { opacity: .55; } }

/* ============ 响应式 ============ */
@media (max-width: 980px) {
  .filters { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .destination { grid-column: span 2; }
  .filters button { min-height: 41px; }
}

@media (max-width: 620px) {
  .discovery-page { padding: 36px 18px 74px; }
  .departure-heading { align-items: start; gap: 18px; }
  .departure-heading h1 { font-size: 52px; }
  .departure-stamp { min-width: 100px; }
  .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .destination { grid-column: 1 / -1; }
  .filters label, .filters select, .filters button { min-height: 42px; }
  .slots { grid-column: span 2; }
  .filters button { grid-column: span 2; }
}

@media (prefers-reduced-motion: reduce) {
  .departure-heading { animation: none; }
  .departure-stamp { transform: none; transition: none; }
  .skeleton { animation: none; }
  .filters button, .state-panel button,
  .filters label, .filters select { transition: none; }
}
</style>
