<script setup lang="ts">
import { computed, ref } from 'vue'
import { createTravelOrder, createTravelSearch, type SearchType, type TravelOffer, type TravelOrderPassenger, type TravelSearchJob } from '../api'
import { useReveal } from '@/composables/useReveal'

type OfferSnapshot = {
  id: string
  title: string
  price: string
  source: string
  availability: string
  validUntil: string
  retrievedAt: string
  changeSummary: string
}

const searchType = ref<SearchType>('train')
const origin = ref('杭州东')
const destination = ref('上海虹桥')
const departDate = ref('2026-10-01')
const passengerCount = ref(1)
const job = ref<TravelSearchJob | null>(null)
const selectedOffer = ref<OfferSnapshot | null>(null)
const passenger = ref<TravelOrderPassenger>({ name: '', document_type: 'identity_card', document_number: '', seat_preference: 'none' })
const loading = ref(false)
const ordering = ref(false)
const error = ref('')
const checkoutMessage = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)

const isTransportSearch = computed(() => searchType.value === 'train' || searchType.value === 'flight')
const searchLabel = computed(() => searchType.value === 'train' ? '搜索火车' : searchType.value === 'flight' ? '搜索航班' : '搜索报价')
const originLabel = computed(() => searchType.value === 'train' ? '出发车站' : '出发城市')
const destinationLabel = computed(() => searchType.value === 'train' ? '到达车站' : '到达城市')
const originPlaceholder = computed(() => searchType.value === 'train' ? '例如杭州东' : '例如杭州')
const destinationPlaceholder = computed(() => searchType.value === 'train' ? '例如上海虹桥' : '例如上海')

function formatDate(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : parsed.toLocaleString()
}

function normalizeOffer(offer: TravelOffer): OfferSnapshot {
  const rules = offer.change_rules && typeof offer.change_rules === 'object' ? offer.change_rules : {}
  const changeSummary = typeof rules.summary === 'string' && rules.summary.trim() ? rules.summary : '改签与退票规则以供应商确认结果为准。'
  return {
    id: offer.id,
    title: offer.title?.trim() || '未命名报价',
    price: `${offer.currency || 'CNY'} ${offer.amount || '0.00'}`,
    source: offer.source?.trim() || '供应商待确认',
    availability: offer.availability === 'available' ? '可预订' : '暂不可预订',
    validUntil: formatDate(offer.valid_until),
    retrievedAt: formatDate(offer.retrieved_at),
    changeSummary,
  }
}

async function search() {
  loading.value = true
  error.value = ''
  checkoutMessage.value = ''
  selectedOffer.value = null
  try {
    job.value = (await createTravelSearch({ search_type: searchType.value, origin: origin.value, destination: destination.value, depart_date: departDate.value, passenger_count: passengerCount.value })).data
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '搜索未完成，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function selectOffer(offer: TravelOffer) {
  if (offer.availability !== 'available') return
  selectedOffer.value = normalizeOffer(offer)
  checkoutMessage.value = ''
}

async function checkout() {
  if (!selectedOffer.value || ordering.value) return
  if (isTransportSearch.value && (!passenger.value.name.trim() || !passenger.value.document_number.trim())) {
    checkoutMessage.value = '请填写乘车人姓名和证件号码后再创建订单。'
    return
  }
  ordering.value = true
  checkoutMessage.value = ''
  try {
    const passengers = isTransportSearch.value ? [{ ...passenger.value, name: passenger.value.name.trim(), document_number: passenger.value.document_number.trim() }] : []
    const { data } = await createTravelOrder(selectedOffer.value.id, passengers)
    checkoutMessage.value = `订单 ${data.order_no} 已创建，请前往订单页继续支付。`
    passenger.value = { name: '', document_type: 'identity_card', document_number: '', seat_preference: 'none' }
  } catch (reason) {
    checkoutMessage.value = reason instanceof Error ? reason.message : '订单未能创建，请确认报价仍然有效后重试。'
  } finally {
    ordering.value = false
  }
}
</script>

<template>
  <main class="travel-search" ref="root">
    <section class="masthead" data-reveal>
      <h1>查询交通报价</h1>
      <p>选择火车或航班，确认报价快照后创建订单。</p>
    </section>
    <form class="search-grid" data-reveal @submit.prevent="search">
      <fieldset class="transport-type">
        <legend>出行方式</legend>
        <label><input v-model="searchType" type="radio" value="train" /> 火车</label>
        <label><input v-model="searchType" type="radio" value="flight" /> 航班</label>
      </fieldset>
      <label class="field">{{ originLabel }}<input v-model="origin" :aria-label="originLabel" :placeholder="originPlaceholder" required /></label>
      <label class="field">{{ destinationLabel }}<input v-model="destination" :aria-label="destinationLabel" :placeholder="destinationPlaceholder" required /></label>
      <p v-if="searchType === 'train'" class="station-hint">请输入具体车站，例如杭州东、上海虹桥；系统会自动解析站码。</p>
      <label class="field">出发日期<input v-model="departDate" type="date" required /></label>
      <label class="field">乘客人数<input v-model.number="passengerCount" min="1" max="9" type="number" required /></label>
      <button class="search-submit" :disabled="loading">{{ loading ? '查询中...' : searchLabel }}</button>
    </form>
    <Transition name="fade">
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </Transition>
    <Transition name="fade">
      <section v-if="job" class="results">
        <header class="results-header">
          <div>
            <h2>可选报价</h2>
            <p>来源：{{ job.source }}，获取于 {{ formatDate(job.retrieved_at) }}</p>
          </div>
        </header>
        <div v-if="job.status === 'empty'" class="unavailable">
          <strong>当前没有可用报价</strong>
          <p>{{ job.unavailable_code === 'SUPPLIER_UNAVAILABLE' || job.unavailable_code === 'REALTIME_TRANSPORT_UNAVAILABLE' ? '供应商服务暂不可用，未展示价格或余量。' : '没有符合条件的报价，请调整查询条件。' }}</p>
        </div>
        <article
          v-for="offer in job.offers"
          :key="offer.id"
          class="offer"
          :class="{ selected: selectedOffer?.id === offer.id }"
        >
          <div class="offer-main">
            <strong>{{ normalizeOffer(offer).title }}</strong>
            <p>供应商：{{ normalizeOffer(offer).source }} · {{ normalizeOffer(offer).availability }}</p>
            <p>报价获取：{{ normalizeOffer(offer).retrievedAt }}</p>
          </div>
          <div class="offer-action">
            <strong>{{ normalizeOffer(offer).price }}</strong>
            <button type="button" :disabled="offer.availability !== 'available'" @click="selectOffer(offer)">{{ selectedOffer?.id === offer.id ? '已选择' : '选择报价' }}</button>
          </div>
        </article>
      </section>
    </Transition>
    <Transition name="slide-up">
      <section v-if="selectedOffer" class="checkout" aria-labelledby="checkout-title">
        <div class="snapshot">
          <h2 id="checkout-title">已选报价快照</h2>
          <strong>{{ selectedOffer.title }}</strong>
          <p>{{ selectedOffer.price }} · {{ selectedOffer.availability }}</p>
          <p>供应商：{{ selectedOffer.source }}</p>
          <p>有效至：{{ selectedOffer.validUntil }}</p>
          <p>{{ selectedOffer.changeSummary }}</p>
        </div>
        <form class="passenger-form" @submit.prevent="checkout">
          <h2>乘客信息</h2>
          <p>此信息仅用于本次创建订单，不会保存在此设备上。</p>
          <template v-if="isTransportSearch">
            <label class="field">姓名<input v-model="passenger.name" autocomplete="name" required /></label>
            <label class="field">证件类型<select v-model="passenger.document_type"><option value="identity_card">身份证</option><option value="passport">护照</option></select></label>
            <label class="field">证件号码<input v-model="passenger.document_number" autocomplete="off" required /></label>
            <label class="field">座位偏好<select v-model="passenger.seat_preference"><option value="none">无偏好</option><option value="window">靠窗</option><option value="aisle">靠过道</option></select></label>
            <p class="seat-disclaimer">座位偏好，最终以出票结果为准</p>
          </template>
          <button class="checkout-submit" :disabled="ordering">{{ ordering ? '创建订单中...' : '创建订单' }}</button>
        </form>
      </section>
    </Transition>
    <Transition name="fade">
      <p v-if="checkoutMessage" class="checkout-message" role="status">{{ checkoutMessage }}</p>
    </Transition>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.travel-search {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1120px;
  padding: 44px 24px 80px;
  position: relative;
}

.travel-search ::-webkit-scrollbar { width: 6px; }
.travel-search ::-webkit-scrollbar-track { background: transparent; }
.travel-search ::-webkit-scrollbar-thumb { background: var(--field-line); border-radius: 3px; transition: background var(--motion-fast) var(--ease-standard); }
.travel-search ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

/* ============ 页头 ============ */
.masthead {
  border: 0;
  border-left: 4px solid var(--field-saffron);
  padding: 12px 0 12px 20px;
}

.masthead h1 {
  font-size: 38px;
  letter-spacing: 0;
  line-height: 1.12;
  margin: 0;
}

.masthead p {
  color: var(--field-muted);
  font-size: 15px;
  line-height: 1.7;
  margin: 8px 0 0;
}

/* ============ 搜索表单 ============ */
.search-grid {
  background: color-mix(in srgb, var(--field-white) 94%, var(--field-teal-soft));
  border: 1px solid color-mix(in srgb, var(--field-line) 75%, var(--field-teal));
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-lift);
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 28px;
  padding: 24px;
}

.field {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 13px;
  font-weight: 700;
  gap: 8px;
}

.search-grid input,
.passenger-form input,
.passenger-form select {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  min-height: 44px;
  padding: 9px 12px;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.search-grid input:hover:not(:disabled),
.passenger-form input:hover:not(:disabled),
.passenger-form select:hover:not(:disabled) { border-color: color-mix(in srgb, var(--field-teal) 50%, var(--field-line)); }

.search-grid input:focus-visible,
.passenger-form input:focus-visible,
.passenger-form select:focus-visible {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.transport-type {
  border: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  grid-column: span 3;
  margin: 0;
  padding: 0;
}

.transport-type legend {
  flex-basis: 100%;
  color: var(--field-ink-soft);
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 7px;
  padding: 0;
}

.transport-type label {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  gap: 6px;
  margin: 0;
  padding: 8px 14px;
  transition: border-color var(--motion-base) var(--ease-standard), background-color var(--motion-base) var(--ease-standard);
}

.transport-type label:hover { border-color: var(--field-teal); }

.transport-type input { accent-color: var(--field-teal); }

.station-hint {
  color: var(--field-muted);
  font-size: 13px;
  grid-column: span 3;
  line-height: 1.5;
  margin: -4px 0 0;
}

/* ============ 搜索按钮 ============ */
.search-submit,
.checkout-submit,
.offer-action button {
  background: var(--field-teal);
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  font-weight: 800;
  font-size: 14px;
  min-height: 44px;
  padding: 0 16px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.search-submit:hover:not(:disabled),
.checkout-submit:hover:not(:disabled),
.offer-action button:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  transform: translateY(-1px);
}

.search-submit:active:not(:disabled),
.checkout-submit:active:not(:disabled),
.offer-action button:active:not(:disabled) { transform: translateY(0) scale(0.98); }

.search-submit:disabled,
.checkout-submit:disabled,
.offer-action button:disabled { cursor: wait; opacity: 0.55; }

.search-submit:focus-visible,
.checkout-submit:focus-visible,
.offer-action button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 报错 ============ */
.error {
  background: var(--field-white);
  border-left: 3px solid var(--field-coral);
  border-radius: 0 var(--travel-radius-sm) var(--travel-radius-sm) 0;
  color: #9c4234;
  margin-top: 20px;
  padding: 14px 16px;
}

/* ============ 结果区 ============ */
.results { margin-top: 42px; }

.results-header {
  border-bottom: 2px solid var(--field-ink);
  padding-bottom: 14px;
}

.results h2,
.checkout h2 {
  font-size: 21px;
  font-weight: 700;
  margin: 0 0 6px;
}

.results p,
.checkout p {
  color: var(--field-muted);
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.unavailable {
  background: color-mix(in srgb, var(--field-coral) 8%, var(--field-white));
  border: 1px solid color-mix(in srgb, var(--field-coral) 30%, var(--field-line));
  border-radius: var(--travel-radius-sm);
  margin-top: 14px;
  padding: 16px;
}

.unavailable strong { color: #9c4234; display: block; font-size: 15px; margin-bottom: 4px; }

.offer {
  align-items: start;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  justify-content: space-between;
  margin-top: 12px;
  padding: 20px;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.offer:hover {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-soft);
}

.offer.selected {
  border-color: var(--field-teal);
  border-left-width: 4px;
}

.offer-main { min-width: 200px; }

.offer strong { color: var(--field-ink); font-size: 16px; }

.offer-main p { margin-top: 6px; }

.offer-action {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.offer-action > strong {
  color: var(--field-coral);
  font-size: 18px;
  font-weight: 700;
}

/* ============ 结算区 ============ */
.checkout {
  background: color-mix(in srgb, var(--field-teal-soft) 55%, var(--field-white));
  border: 1px solid color-mix(in srgb, var(--field-teal) 35%, var(--field-line));
  border-radius: var(--travel-radius);
  display: grid;
  gap: 28px;
  margin-top: 34px;
  padding: 24px;
}

.snapshot {
  border-left: 3px solid var(--field-saffron);
  padding-left: 16px;
}

.snapshot strong { color: var(--field-ink); display: block; font-size: 17px; margin: 6px 0; }

.passenger-form {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: grid;
  gap: 14px;
  padding: 20px;
}

.passenger-form h2 { font-size: 17px; }

.seat-disclaimer {
  color: var(--field-muted);
  font-size: 12px;
  margin: -4px 0 0;
}

.checkout-message {
  background: var(--field-white);
  border-left: 3px solid var(--field-teal);
  border-radius: 0 var(--travel-radius-sm) var(--travel-radius-sm) 0;
  color: var(--field-ink);
  margin-top: 20px;
  padding: 12px 16px;
}

/* ============ 响应式 ============ */
@media (max-width: 700px) {
  .travel-search { padding: 28px 16px 56px; }
  .masthead h1 { font-size: 30px; }
  .search-grid { grid-template-columns: 1fr; padding: 18px; }
  .transport-type,
  .station-hint { grid-column: auto; }
  .offer,
  .checkout { align-items: stretch; flex-direction: column; }
  .offer-action { align-items: stretch; }
  .offer-action button { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .offer,
  .search-submit,
  .checkout-submit,
  .offer-action button,
  .transport-type label,
  .search-grid input,
  .passenger-form input,
  .passenger-form select { transition: none; }
}
</style>
