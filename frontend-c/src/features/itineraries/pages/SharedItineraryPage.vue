<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { LockKeyhole, MapPinned } from 'lucide-vue-next'
import { getSharedItinerary, type ItinerarySnapshot } from '../api'
import Timeline from '../components/Timeline.vue'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ itineraryId: string }>()
const route = useRoute()
const snapshot = ref<ItinerarySnapshot | null>(null)
const title = ref('共享行程')
const unavailable = ref(false)
const activeDay = ref(0)
const day = computed(() => snapshot.value?.days[activeDay.value])
const root = ref<HTMLElement | null>(null)
useReveal(root)

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) { unavailable.value = true; return }
  try {
    const itinerary = await getSharedItinerary(props.itineraryId, token)
    title.value = itinerary.title
    snapshot.value = itinerary.snapshot
  } catch {
    unavailable.value = true
  }
})
</script>

<template>
  <main class="shared-page" ref="root">
    <header class="shared-header">
      <div class="shared-header__intro">
        <p class="eyebrow">SHARED ITINERARY</p>
        <h1>{{ title }}</h1>
      </div>
      <span class="readonly-badge"><LockKeyhole :size="15" />只读分享</span>
    </header>
    <section v-if="unavailable" class="notice" role="alert">
      <strong>此分享链接不可用。</strong>
      <span>它可能已撤销、过期，或地址不完整。</span>
    </section>
    <template v-else-if="snapshot">
      <nav v-if="snapshot.days.length" class="day-tabs" aria-label="行程日期" data-reveal>
        <button v-for="(item, index) in snapshot.days" :key="item.id" :class="{ active: activeDay === index }" type="button" :aria-current="activeDay === index ? 'true' : undefined" @click="activeDay = index">第 {{ index + 1 }} 天 · {{ item.day_date }}</button>
      </nav>
      <Timeline v-if="day" :day="day" :active="true" readonly />
    </template>
    <section v-else class="loading" role="status" aria-live="polite">
      <MapPinned :size="19" />
      <span>正在打开共享行程。</span>
    </section>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.shared-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 900px;
  min-height: calc(100vh - 70px);
  padding: 48px 24px 80px;
}

/* ============ 页头 ============ */
.shared-header {
  align-items: flex-end;
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  display: flex;
  gap: 18px;
  justify-content: space-between;
  padding-bottom: 28px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.shared-header__intro { min-width: 0; }

.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 10px;
  text-transform: uppercase;
}

.shared-header h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(34px, 5vw, 54px);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
  margin: 0;
}

.readonly-badge {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  display: inline-flex;
  flex: 0 0 auto;
  font: 700 12px var(--field-mono);
  gap: 6px;
  letter-spacing: 0.04em;
  padding: 9px 13px;
}

/* ============ 不可用提示 ============ */
.notice {
  background: #fff0eb;
  border-left: 3px solid var(--field-coral);
  border-radius: 4px;
  color: #9c4234;
  display: grid;
  gap: 6px;
  margin-top: 28px;
  padding: 18px 20px;
}

.notice strong {
  color: #9c4234;
  font-size: 15px;
  font-weight: 700;
}

.notice span {
  color: #9c4234;
  font-size: 13px;
  line-height: 1.6;
  opacity: 0.85;
}

/* ============ 日期切换 ============ */
.day-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 28px 0;
}

.day-tabs button {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: 999px;
  color: var(--field-ink-soft);
  cursor: pointer;
  flex: 0 0 auto;
  font: 700 13px inherit;
  padding: 9px 14px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-fast) var(--ease-standard);
}

.day-tabs button:hover {
  background: var(--field-teal-soft);
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-1px);
}

.day-tabs button:active { transform: scale(0.97); }

.day-tabs button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.day-tabs button.active {
  background: var(--field-teal);
  border-color: var(--field-teal);
  color: var(--field-white);
}

.day-tabs button.active:hover {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
}

/* ============ 加载态 ============ */
.loading {
  align-items: center;
  background: var(--field-white);
  border: 1px dashed var(--field-line);
  border-radius: var(--travel-radius);
  color: var(--field-muted);
  display: flex;
  font-size: 14px;
  gap: 10px;
  margin-top: 28px;
  padding: 28px 24px;
}

.loading svg { color: var(--field-teal); }

/* ============ 响应式 ============ */
@media (max-width: 640px) {
  .shared-page { padding: 36px 16px 64px; }
  .shared-header { align-items: flex-start; flex-direction: column; gap: 16px; }
  .shared-header h1 { font-size: 34px; }
  .day-tabs { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; }
}

/* ============ 减少动效 ============ */
@media (prefers-reduced-motion: reduce) {
  .shared-header,
  .day-tabs button {
    animation: none !important;
    transition: none !important;
  }
  .day-tabs button:hover { transform: none !important; }
}
</style>
