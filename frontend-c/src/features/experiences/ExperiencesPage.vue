<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, Compass, MapPin, RefreshCw, Ticket } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { useReveal } from '@/composables/useReveal'
import { listExperiences, type ExperienceSummary } from './api'

const experiences = ref<ExperienceSummary[]>([])
const loading = ref(true)
const unavailable = ref(false)
const activeProvider = ref<string | undefined>()

const providers = computed(() => Array.from(new Map(experiences.value.map((experience) => [experience.provider.id, experience.provider])).values()))
const visibleExperiences = computed(() => activeProvider.value
  ? experiences.value.filter((experience) => experience.provider.id === activeProvider.value)
  : experiences.value)

function formatPrice(experience: ExperienceSummary) {
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: experience.currency, maximumFractionDigits: 0 }).format(Number(experience.price_amount))
}

async function loadExperiences() {
  loading.value = true
  unavailable.value = false
  try {
    experiences.value = (await listExperiences()).items
  } catch {
    unavailable.value = true
  } finally {
    loading.value = false
  }
}

const root = ref<HTMLElement | null>(null)
useReveal(root)
onMounted(loadExperiences)
</script>

<template>
  <main class="catalog-page" ref="root">
    <header class="catalog-masthead">
      <div>
        <h1>体验目录</h1>
        <p>由服务商发布的在地体验。先了解地点、场次与取消说明，再决定是否纳入你的旅行计划。</p>
      </div>
      <div class="masthead-mark" aria-hidden="true"><Compass :size="30" /><span>FIELD<br />PICKS</span></div>
    </header>

    <section v-if="loading" class="state-panel" aria-live="polite">
      <RefreshCw class="spin" :size="22" /><div><h2>正在整理体验目录</h2><p>正在读取已发布的体验信息。</p></div>
    </section>

    <section v-else-if="unavailable" class="state-panel state-unavailable" role="alert">
      <div><h2>体验目录暂时不可用</h2><p>目前无法取得服务商发布的信息。请稍后重试，目录恢复后不会自动产生预约。</p></div>
      <button type="button" @click="loadExperiences"><RefreshCw :size="16" />重新读取</button>
    </section>

    <template v-else>
      <section v-if="experiences.length" class="catalog-tools" aria-label="Experience catalog filters" data-reveal>
        <p>{{ experiences.length }} 个已发布体验</p>
        <div class="provider-filters">
          <button type="button" :class="{ selected: !activeProvider }" :aria-pressed="!activeProvider" @click="activeProvider = undefined">全部服务商</button>
          <button v-for="provider in providers" :key="provider.id" type="button" :class="{ selected: activeProvider === provider.id }" :aria-pressed="activeProvider === provider.id" @click="activeProvider = provider.id">{{ provider.name }}</button>
        </div>
      </section>

      <section v-if="visibleExperiences.length" class="experience-list" aria-label="Published experiences">
        <RouterLink v-for="(experience, index) in visibleExperiences" :key="experience.id" class="experience-row" :style="{ '--reveal-index': index }" :to="`/experiences/${experience.id}`">
          <span class="row-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="experience-title"><h2>{{ experience.title }}</h2><p><MapPin :size="15" />{{ experience.provider.name }}</p></div>
          <div class="experience-price"><span>起价</span><strong>{{ formatPrice(experience) }}</strong></div>
          <ArrowRight class="row-arrow" :size="20" aria-hidden="true" />
        </RouterLink>
      </section>

      <section v-else class="state-panel">
        <Ticket :size="24" /><div><h2>这个服务商暂时没有已发布体验</h2><p>切换到全部服务商，查看其他可浏览的体验。</p></div>
      </section>

      <section v-if="!experiences.length" class="empty-ledger">
        <Ticket :size="30" /><h2>还没有可浏览的体验</h2><p>服务商发布体验后，会在这里公开显示。此页面只提供浏览与信息查阅。</p>
      </section>
    </template>
  </main>
</template>

<style scoped>
.catalog-page { margin: 0 auto; max-width: 1240px; padding: 48px 28px 90px; }
.catalog-masthead { align-items: end; background: linear-gradient(90deg, rgba(10,38,54,.9), rgba(10,38,54,.25)), url('https://images.unsplash.com/photo-1528164344705-47542687000d?auto=format&fit=crop&w=2000&q=85') center/cover; color: #fff; display: flex; justify-content: space-between; min-height: 410px; padding: 48px; animation: masthead-enter var(--motion-slow) var(--ease-out) both; }
@keyframes masthead-enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
.catalog-masthead h1 { font-size: clamp(38px, 5vw, 67px); letter-spacing: 0; line-height: 1.1; margin: 0; }
.catalog-masthead p { color: #d9eaeb; font-size: 16px; line-height: 1.75; margin: 20px 0 0; max-width: 560px; }
.masthead-mark { align-items: center; background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.45); color: #fff; display: flex; font: 700 11px/1.3 var(--field-mono); gap: 10px; padding: 14px; }
.masthead-mark svg { color: #ff9a81; }
.catalog-tools { align-items: center; border-bottom: 1px solid var(--field-line); display: flex; gap: 24px; justify-content: space-between; padding: 28px 0; }
.catalog-tools > p { color: var(--field-muted); font: 700 12px var(--field-mono); margin: 0; }
.provider-filters { display: flex; flex-wrap: wrap; gap: 8px; justify-content: end; }
.provider-filters button { background: transparent; border: 1px solid var(--field-line); border-radius: 7px; color: var(--field-ink); cursor: pointer; font-size: 13px; font-weight: 700; padding: 9px 12px; transition: background-color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }
.provider-filters button:hover { border-color: var(--field-teal); color: var(--field-teal); transform: translateY(-1px); }
.provider-filters button:active { transform: scale(0.97); }
.provider-filters button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.provider-filters button.selected { background: var(--field-coral); border-color: var(--field-coral); color: #fff; }
.provider-filters button.selected:hover { background: #e6785f; color: #fff; }
.experience-list { margin-top: 26px; }
.experience-row { align-items: center; border-bottom: 1px solid var(--field-line); color: var(--field-ink); display: grid; gap: 22px; grid-template-columns: 48px minmax(0, 1fr) 128px 24px; opacity: 0; padding: 30px 15px; text-decoration: none; transform: translateY(12px); transition: background-color var(--motion-fast) var(--ease-standard), padding var(--motion-fast) var(--ease-standard), opacity var(--motion-slow) var(--ease-out), transform var(--motion-slow) var(--ease-out); transition-delay: calc(var(--reveal-index, 0) * 60ms); }
.experience-list .experience-row { opacity: 1; transform: none; }
.experience-row:hover { background: var(--travel-sky); padding-left: 22px; }
.experience-row:hover h2 { color: var(--field-teal); }
.experience-row:active { transform: scale(0.99); }
.experience-row:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: -3px; }
.row-index { color: var(--field-saffron); font: 800 13px var(--field-mono); }
.experience-title h2 { font-size: 22px; line-height: 1.3; margin: 0; transition: color var(--motion-fast) var(--ease-standard); }
.experience-title p { align-items: center; color: var(--field-muted); display: flex; font-size: 13px; gap: 5px; margin: 7px 0 0; }
.experience-price { text-align: right; }
.experience-price span { color: var(--field-muted); display: block; font: 700 10px var(--field-mono); margin-bottom: 3px; }
.experience-price strong { color: var(--field-ink); font-size: 19px; }
.row-arrow { color: var(--field-coral); transition: transform var(--motion-base) var(--ease-out); }
.experience-row:hover .row-arrow { transform: translateX(4px); }
.state-panel { align-items: center; background: var(--field-white); border: 1px solid var(--field-line); border-radius: 12px; color: var(--field-ink-soft); display: flex; gap: 18px; margin-top: 28px; padding: 42px 32px; }
.state-panel svg { color: var(--field-teal); flex: 0 0 auto; }
.state-panel h2 { font-size: 19px; margin: 0; }
.state-panel p { color: var(--field-muted); line-height: 1.65; margin: 7px 0 0; }
.state-panel button { align-items: center; background: var(--field-deep); border: 0; border-radius: 8px; color: #fff; cursor: pointer; display: inline-flex; font-weight: 800; gap: 7px; margin-top: 14px; padding: 10px 16px; transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard); }
.state-panel button:hover { background: var(--field-teal); transform: translateY(-1px); }
.state-panel button:active { transform: scale(0.97); }
.state-panel button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.state-unavailable { border-left: 4px solid var(--field-coral); flex-direction: column; text-align: center; }
.empty-ledger { align-items: center; background: var(--travel-sand); border-radius: 12px; color: var(--field-ink-soft); display: flex; flex-direction: column; gap: 14px; margin-top: 28px; padding: 64px 28px; text-align: center; }
.empty-ledger svg { color: var(--field-saffron); }
.empty-ledger h2 { font-size: 22px; margin: 0; }
.empty-ledger p { color: var(--field-muted); line-height: 1.7; margin: 0; max-width: 44ch; }
.spin { color: var(--field-teal); }
@media (max-width: 700px) {
  .catalog-page { padding: 28px 16px 56px; }
  .catalog-masthead { align-items: start; flex-direction: column; min-height: 260px; padding: 28px 24px; }
  .catalog-masthead h1 { font-size: 39px; }
  .catalog-tools { align-items: start; flex-direction: column; }
  .provider-filters { justify-content: start; }
  .experience-row { gap: 12px; grid-template-columns: 34px minmax(0, 1fr) 20px; }
  .experience-price { grid-column: 2; text-align: left; }
  .row-arrow { grid-column: 3; grid-row: 1 / span 2; }
  .state-unavailable { align-items: start; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  .catalog-masthead, .experience-row { animation: none; transition: none; transform: none; opacity: 1; }
  .provider-filters button, .state-panel button { transition: none; transform: none; }
  .spin { animation: none; }
}
</style>
