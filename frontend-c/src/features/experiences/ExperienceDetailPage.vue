<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, CalendarDays, MapPin, RefreshCw, ShieldCheck, Users } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { useReveal } from '@/composables/useReveal'
import { getExperience, type ExperienceDetail, type ExperienceSession } from './api'
const props = defineProps<{ experienceId: string }>()
const experience = ref<ExperienceDetail | null>(null); const loading = ref(true); const unavailable = ref(false)
const scheduledSessions = computed(() => experience.value?.sessions.filter((session) => session.status === 'scheduled') ?? [])
function formatPrice(item: ExperienceDetail) { return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: item.currency, maximumFractionDigits: 0 }).format(Number(item.price_amount)) }
function formatSession(session: ExperienceSession) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(session.starts_at)) }
async function loadExperience() { loading.value = true; unavailable.value = false; experience.value = null; try { experience.value = await getExperience(props.experienceId) } catch { unavailable.value = true } finally { loading.value = false } }
const root = ref<HTMLElement | null>(null)
useReveal(root)
onMounted(loadExperience); watch(() => props.experienceId, loadExperience)
</script>
<template><main class="detail-page" ref="root"><RouterLink class="back-link" to="/experiences"><ArrowLeft :size="16" />返回在地体验</RouterLink><section v-if="loading" class="state-panel" aria-live="polite"><RefreshCw class="spin" :size="22" /><div><h1>正在读取体验详情</h1><p>正在整理服务商发布的场次和说明。</p></div></section><section v-else-if="unavailable" class="state-panel unavailable" role="alert"><div><h1>这项体验暂时无法查看</h1><p>它可能已下架，或体验信息暂时不可用。返回目录查看其他已发布体验。</p></div><button type="button" @click="loadExperience"><RefreshCw :size="16" />重新读取</button></section><template v-else-if="experience"><header class="detail-header" data-reveal style="--reveal-index:0"><div><p class="provider-name">HOSTED BY {{ experience.provider.name }}</p><h1>{{ experience.title }}</h1><p class="header-note">留出一点时间，走进目的地更日常的一面。</p></div><div class="price-stamp"><span>参考起价</span><strong>{{ formatPrice(experience) }}</strong><small>以服务商最终说明为准</small></div></header><div class="detail-grid"><article class="main-copy" data-reveal style="--reveal-index:1"><p class="section-label">THE EXPERIENCE</p><h2>这一天，值得怎么度过？</h2><p>{{ experience.description }}</p><section v-if="experience.meeting_point" class="information-row"><MapPin :size="19" /><div><h2>集合地点</h2><p>{{ experience.meeting_point }}</p></div></section></article><aside class="session-ledger" aria-labelledby="session-title" data-reveal style="--reveal-index:2"><div class="ledger-heading"><div><h2 id="session-title">公开场次</h2><p>场次只供查看，不在此页面预约或支付。</p></div><CalendarDays :size="21" /></div><div v-if="scheduledSessions.length" class="sessions"><div v-for="session in scheduledSessions" :key="session.id" class="session-row"><time :datetime="session.starts_at">{{ formatSession(session) }}</time><span><Users :size="15" />还剩 {{ session.remaining_capacity }} 位</span></div></div><div v-else class="no-sessions"><CalendarDays :size="20" /><p>目前没有可公开查看的后续场次。</p></div></aside></div><section class="policy-panel" data-reveal style="--reveal-index:3"><ShieldCheck :size="22" /><div><h2>取消说明</h2><p>{{ experience.cancellation_policy }}</p></div></section></template></main></template>
<style scoped>
.detail-page { margin: 0 auto; max-width: 1140px; padding: 42px 28px 92px; }
.back-link { align-items: center; color: var(--field-teal); display: inline-flex; font-size: 13px; font-weight: 800; gap: 7px; padding: 8px 12px; border-radius: 8px; text-decoration: none; transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }
.back-link:hover { color: var(--field-coral); background: var(--travel-sky); transform: translateX(-2px); }
.back-link:active { transform: scale(0.97); }
.back-link:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }
.detail-header { align-items: end; background: linear-gradient(120deg, #e0f0ee, #fff); border-bottom: 3px solid var(--field-teal); display: flex; gap: 30px; justify-content: space-between; margin-top: 28px; padding: 45px; }
.provider-name, .section-label { color: var(--field-teal); font: 800 11px var(--field-mono); letter-spacing: .1em; margin: 0 0 14px; }
.detail-header h1 { font-size: clamp(38px, 5vw, 66px); letter-spacing: 0; line-height: 1.12; margin: 0; max-width: 710px; }
.header-note { color: var(--field-ink-soft); line-height: 1.65; margin: 18px 0 0; }
.price-stamp { background: #fff; border-top: 3px solid var(--field-coral); display: grid; gap: 5px; min-width: 190px; padding: 17px; transition: transform var(--motion-base) var(--ease-out), box-shadow var(--motion-base) var(--ease-out); }
.price-stamp:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); }
.price-stamp span, .price-stamp small { color: var(--field-muted); font-size: 11px; }
.price-stamp strong { font-size: 25px; }
.detail-grid { display: grid; gap: 62px; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); padding: 58px 0; }
.main-copy > h2 { font-size: 32px; line-height: 1.3; margin: 0; }
.session-ledger h2, .policy-panel h2 { font-size: 20px; margin: 0; }
.main-copy > p:not(.section-label) { font-size: 17px; line-height: 1.9; margin: 20px 0 0; white-space: pre-line; }
.information-row { align-items: start; border-top: 1px solid var(--field-line); display: flex; gap: 12px; margin-top: 44px; padding-top: 21px; }
.information-row svg { color: var(--field-coral); }
.information-row p, .policy-panel p { color: var(--field-ink-soft); font-size: 14px; line-height: 1.65; margin: 8px 0 0; }
.session-ledger { align-self: start; background: var(--field-deep); border-bottom: 4px solid var(--field-coral); color: #fff; padding: 25px; }
.ledger-heading { align-items: start; color: #fff; display: flex; justify-content: space-between; gap: 12px; }
.ledger-heading p { color: #b8d0d2; font-size: 12px; line-height: 1.55; margin: 8px 0 0; }
.ledger-heading > svg { color: #ff9a81; }
.sessions { border-top: 1px solid #45636d; margin-top: 24px; }
.session-row { align-items: center; border-bottom: 1px solid #45636d; display: flex; gap: 14px; justify-content: space-between; padding: 13px 0; transition: background-color var(--motion-fast) var(--ease-standard); }
.session-row:hover { background: rgba(255, 255, 255, .04); }
.session-row time { font: 700 13px var(--field-mono); }
.session-row span { align-items: center; color: #b8d0d2; display: inline-flex; font-size: 12px; gap: 5px; }
.session-row svg { color: #ff9a81; }
.no-sessions { align-items: center; color: #b8d0d2; display: flex; flex-direction: column; gap: 12px; padding: 34px 0 8px; text-align: center; }
.no-sessions svg { color: #45636d; }
.policy-panel { align-items: start; background: var(--travel-sand); border-left: 4px solid var(--field-saffron); display: flex; gap: 16px; margin-top: 12px; padding: 26px 30px; }
.policy-panel svg { color: var(--field-saffron); }
.state-panel { align-items: center; background: var(--field-white); border: 1px solid var(--field-line); border-radius: 12px; color: var(--field-ink-soft); display: flex; flex-direction: column; gap: 18px; margin-top: 28px; padding: 64px 28px; text-align: center; }
.state-panel.unavailable { border-left: 4px solid var(--field-coral); }
.state-panel h1 { font-size: 22px; margin: 0; }
.state-panel p { color: var(--field-muted); line-height: 1.7; margin: 8px 0 0; max-width: 42ch; }
.state-panel button { align-items: center; background: var(--field-deep); border: 0; border-radius: 8px; color: #fff; cursor: pointer; display: inline-flex; font-weight: 800; gap: 7px; padding: 11px 18px; transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard); }
.state-panel button:hover { background: var(--field-teal); transform: translateY(-1px); }
.state-panel button:active { transform: scale(0.97); }
.state-panel button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }
.state-panel .spin { color: var(--field-teal); }
@media (max-width: 860px) {
  .detail-header { flex-direction: column; padding: 32px; }
  .price-stamp { min-width: 0; }
  .detail-grid { gap: 38px; grid-template-columns: 1fr; padding: 38px 0; }
}
@media (max-width: 520px) {
  .detail-page { padding: 28px 18px 64px; }
  .detail-header { padding: 26px 20px; }
  .main-copy > h2 { font-size: 26px; }
  .policy-panel { padding: 20px; }
}
@media (prefers-reduced-motion: reduce) {
  .back-link, .price-stamp, .session-row, .state-panel button { transition: none; transform: none; }
  [data-reveal] { opacity: 1 !important; transform: none !important; }
}
</style>
