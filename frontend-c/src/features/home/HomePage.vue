<script setup lang="ts">
import { ref } from 'vue'
import { ArrowUpRight, CalendarDays, Compass, MapPinned, PenLine, Sparkles } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useReveal } from '@/composables/useReveal'

const auth = useAuthStore()
const root = ref<HTMLElement | null>(null)
useReveal(root)
const templates = [
  { title: '海边慢行', meta: '3 天 · 海岸与小城', color: 'coast', mark: 'COAST' },
  { title: '城市漫游', meta: '2 天 · 步行与街区', color: 'city', mark: 'CITY' },
  { title: '山野留白', meta: '5 天 · 公路与自然', color: 'wild', mark: 'FIELD' },
]
</script>

<template>
  <main class="home-page" ref="root">
    <section class="hero" aria-labelledby="home-title">
      <div class="hero-shade"></div>
      <div class="hero-content">
        <p class="eyebrow hero-stagger" style="--reveal-index:0"><Compass :size="14" />出发的理由</p>
        <h1 id="home-title" class="hero-stagger" style="--reveal-index:1">去远方之前，<br /><i>先遇见它。</i></h1>
        <p class="hero-description hero-stagger" style="--reveal-index:2">从一处海岸、一条旧巷，或一顿惦记已久的晚饭开始。把心动收进路线，让旅程自然生长。</p>
        <div class="hero-actions hero-stagger" style="--reveal-index:3">
          <RouterLink class="primary-action" to="/plan"><PenLine :size="17" />开始一段旅行</RouterLink>
          <RouterLink class="text-action" to="/community">浏览旅行灵感 <ArrowUpRight :size="16" /></RouterLink>
        </div>
        <p class="hero-note hero-stagger" style="--reveal-index:4"><span></span>{{ auth.isConsumerSession ? '你的下一段行程，随时可以继续。' : '不必准备周全，先写下想去的地方。' }}</p>
      </div>
      <div class="hero-location hero-stagger" style="--reveal-index:3"><span>22° 31' N</span><strong>海南 · 万宁</strong><small>日落之后，海还没有睡</small></div>
    </section>

    <section class="route-preview" aria-labelledby="preview-title" data-reveal>
      <header class="section-heading"><div><p class="eyebrow">TRAVEL, AT YOUR PACE</p><h2 id="preview-title">把零散的向往，<br />变成一条自己的路。</h2></div><RouterLink class="quiet-link" to="/plan">进入行程工作台 <ArrowUpRight :size="16" /></RouterLink></header>
      <div class="preview-grid">
        <article :style="{ '--reveal-index': 0 }"><span class="step">01</span><Sparkles :size="22" /><h3>收下灵感</h3><p>一篇游记、一间小店，或朋友随口提起的地方，都值得记下来。</p></article>
        <article :style="{ '--reveal-index': 1 }"><span class="step">02</span><CalendarDays :size="22" /><h3>安排日子</h3><p>在地图与时间之间慢慢取舍，旅程会保留每一次改变。</p></article>
        <article :style="{ '--reveal-index': 2 }"><span class="step">03</span><MapPinned :size="22" /><h3>一起出发</h3><p>把同一份路线交给同行的人，让相见从计划里开始。</p></article>
      </div>
    </section>

    <section class="template-section" aria-labelledby="template-title" data-reveal>
      <header class="section-heading"><div><p class="eyebrow">A GENTLE START</p><h2 id="template-title">从一个偏好开始，<br />而不是一张空白表格。</h2></div></header>
      <div class="template-strip"><RouterLink v-for="(template, index) in templates" :key="template.title" class="template-item" :class="template.color" :style="{ '--reveal-index': index }" :to="'/plan'"><span class="template-mark">{{ template.mark }}</span><div><strong>{{ template.title }}</strong><small>{{ template.meta }}</small></div><ArrowUpRight :size="20" /></RouterLink></div>
    </section>
  </main>
</template>

<style scoped>
.home-page { background: var(--field-paper); color: var(--field-ink); overflow: hidden; }
.hero { background: url('https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=2200&q=88') center/cover; isolation: isolate; min-height: min(720px, calc(100vh - 70px)); padding: clamp(48px, 8vw, 124px); position: relative; display: flex; align-items: center; }
.hero-shade { background: linear-gradient(90deg, rgba(10, 37, 54, .92) 0%, rgba(10, 37, 54, .67) 38%, rgba(10, 37, 54, .05) 76%); inset: 0; position: absolute; z-index: -1; }
.hero-content { color: #fff; max-width: 620px; }
.eyebrow { align-items: center; color: var(--field-teal); display: flex; font: 800 11px/1.2 var(--field-mono); gap: 7px; letter-spacing: .1em; margin: 0; }
.hero .eyebrow { color: #8ed6d2; }
.hero h1 { font-size: clamp(48px, 6.5vw, 86px); letter-spacing: 0; line-height: 1.05; margin: 22px 0; }
.hero h1 i { color: #ff9a81; font-style: normal; }
.hero-description { color: #d5e4e9; font-size: 17px; line-height: 1.8; max-width: 460px; }
.hero-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 22px; margin-top: 34px; }
.primary-action, .text-action, .quiet-link { align-items: center; display: inline-flex; font-weight: 800; gap: 8px; text-decoration: none; }
.primary-action { background: var(--field-coral); color: #fff; padding: 14px 19px; transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard); }
.primary-action:hover { background: #e67960; transform: translateY(-2px); box-shadow: 0 10px 24px rgba(216, 110, 88, .35); }
.primary-action:active { transform: translateY(0) scale(0.97); }
.text-action { color: #fff; font-size: 14px; transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }
.text-action:hover { color: #ffab94; transform: translateX(2px); }
.text-action:active { transform: scale(0.97); }
.hero-note { align-items: center; color: #b8d0d7; display: flex; font-size: 12px; gap: 8px; margin: 42px 0 0; }
.hero-note span { background: var(--field-coral); border-radius: 50%; height: 7px; width: 7px; animation: pulse-dot 2.4s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.8); } }
.hero-location { bottom: 40px; color: #fff; display: grid; gap: 5px; position: absolute; right: clamp(28px, 7vw, 100px); text-align: right; }
.hero-location span { color: #9cd7d4; font: 800 10px var(--field-mono); }
.hero-location strong { font-size: 15px; }
.hero-location small { color: #d2e2e4; font-size: 12px; }
.route-preview, .template-section { margin: 0 auto; max-width: 1240px; padding: 94px 28px; }
.section-heading { align-items: end; display: flex; gap: 30px; justify-content: space-between; }
.section-heading h2 { font-size: clamp(30px, 4vw, 52px); letter-spacing: 0; line-height: 1.2; margin: 15px 0 0; }
.quiet-link { color: var(--field-teal); font-size: 13px; white-space: nowrap; transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }
.quiet-link:hover { color: var(--field-coral); transform: translateX(3px); }
.quiet-link:active { transform: scale(0.97); }
.preview-grid { display: grid; gap: 0; grid-template-columns: repeat(3, 1fr); margin-top: 50px; }
.preview-grid article { border-top: 1px solid var(--field-line); min-height: 240px; padding: 22px 28px 12px 0; position: relative; transition: transform var(--motion-base) var(--ease-out); }
.preview-grid article + article { border-left: 1px solid var(--field-line); padding-left: 28px; }
.preview-grid article:hover { transform: translateY(-4px); }
.preview-grid svg { color: var(--field-coral); margin: 36px 0 20px; transition: transform var(--motion-base) var(--ease-out); }
.preview-grid article:hover svg { transform: scale(1.12) rotate(-6deg); }
.step { color: var(--field-muted); font: 800 11px var(--field-mono); }
.preview-grid h3 { font-size: 21px; margin: 0; transition: color var(--motion-fast) var(--ease-standard); }
.preview-grid article:hover h3 { color: var(--field-teal); }
.preview-grid p { color: var(--field-ink-soft); font-size: 14px; line-height: 1.7; margin: 10px 0; max-width: 290px; }
.template-section { padding-top: 12px; }
.template-strip { display: grid; gap: 14px; grid-template-columns: repeat(3, 1fr); margin-top: 44px; }
.template-item { aspect-ratio: 1.28; color: #fff; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; padding: 24px; position: relative; text-decoration: none; transition: transform var(--motion-base) var(--ease-out), box-shadow var(--motion-base) var(--ease-out); }
.template-item::before { background: rgba(8, 35, 49, .34); content: ''; inset: 0; position: absolute; transition: background var(--motion-base) var(--ease-standard); }
.template-item > * { position: relative; }
.template-item.coast { background: url('https://images.unsplash.com/photo-1475924156734-496f6cac6ec1?auto=format&fit=crop&w=900&q=80') center/cover; }
.template-item.city { background: url('https://images.unsplash.com/photo-1528360983277-13d401cdc186?auto=format&fit=crop&w=900&q=80') center/cover; }
.template-item.wild { background: url('https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=900&q=80') center/cover; }
.template-item:hover { transform: translateY(-6px); box-shadow: 0 18px 38px rgba(19, 43, 58, .28); }
.template-item:hover::before { background: rgba(8, 35, 49, .18); }
.template-item:active { transform: translateY(-2px) scale(0.99); }
.template-mark { font: 800 11px var(--field-mono); letter-spacing: .12em; }
.template-item strong { display: block; font-size: 28px; margin-bottom: 7px; }
.template-item small { font-size: 13px; }
.template-item svg { align-self: end; transition: transform var(--motion-base) var(--ease-out); }
.template-item:hover svg { transform: translate(3px, -3px); }
.primary-action:focus-visible, .text-action:focus-visible, .quiet-link:focus-visible, .template-item:focus-visible { outline-color: #fff; }

/* hero 入场错峰：仅一次性，opacity + translateY，prefers-reduced-motion 下全局已降级 */
.hero-stagger { animation: hero-enter var(--motion-slow) var(--ease-out) both; animation-delay: calc(var(--reveal-index, 0) * 110ms); }
@keyframes hero-enter { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
/* preview-grid / template-strip 子项随父 data-reveal 触发后错峰 */
.preview-grid article, .template-strip .template-item { opacity: 0; transform: translateY(14px); transition: opacity var(--motion-slow) var(--ease-out), transform var(--motion-slow) var(--ease-out), box-shadow var(--motion-base) var(--ease-out); transition-delay: calc(var(--reveal-index, 0) * 80ms); }
.route-preview.is-revealed .preview-grid article,
.template-section.is-revealed .template-strip .template-item { opacity: 1; transform: none; }
.route-preview.is-revealed .preview-grid article:hover,
.template-section.is-revealed .template-strip .template-item:hover { transform: translateY(-6px); }

@media (max-width: 760px) {
  .hero { align-items: end; min-height: 650px; padding: 42px 24px 100px; }
  .hero-shade { background: linear-gradient(0deg, rgba(10, 37, 54, .94), rgba(10, 37, 54, .2)); }
  .hero-location { bottom: 30px; left: 24px; right: auto; text-align: left; }
  .route-preview, .template-section { padding: 64px 20px; }
  .section-heading { align-items: start; flex-direction: column; gap: 20px; }
  .preview-grid, .template-strip { grid-template-columns: 1fr; }
  .preview-grid article + article { border-left: 0; padding-left: 0; }
  .preview-grid article { min-height: 190px; }
  .template-item { aspect-ratio: 1.55; }
  .hero h1 { font-size: 48px; }
}

@media (prefers-reduced-motion: reduce) {
  .hero-stagger { animation: none; }
  .hero-note span { animation: none; }
  .preview-grid article, .template-strip .template-item { opacity: 1; transform: none; transition: none; }
}
</style>
