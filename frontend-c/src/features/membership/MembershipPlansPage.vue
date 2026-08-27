<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check, CircleAlert, RefreshCw, Sparkles } from 'lucide-vue-next'
import { createMembershipPurchase, listPublishedMembershipPlans, type MembershipPlan } from './api'
import { normalizeApiError } from '@/services/api'

const plans = ref<MembershipPlan[]>([])
const loading = ref(true)
const error = ref('')
const purchasing = ref('')
const router = useRouter()

function price(plan: MembershipPlan) {
  return `${plan.currency === 'CNY' ? '¥' : plan.currency}${Number(plan.price_amount).toFixed(2)}`
}

async function loadPlans() {
  loading.value = true
  error.value = ''
  try {
    plans.value = await listPublishedMembershipPlans()
  } catch (cause) {
    error.value = normalizeApiError(cause).message
  } finally {
    loading.value = false
  }
}

async function purchase(plan: MembershipPlan) {
  if (!plan.purchasable || purchasing.value) return
  purchasing.value = plan.id
  try {
    const created = await createMembershipPurchase(plan.id, crypto.randomUUID())
    await router.push(`/memberships/pay/${created.id}`)
  } catch (cause) {
    error.value = normalizeApiError(cause).message
    purchasing.value = ''
  }
}

onMounted(() => { void loadPlans() })
</script>

<template>
  <main class="membership-page" :aria-busy="loading">
    <header class="page-header">
      <div class="page-header__intro">
        <p class="eyebrow">AI 规划会员</p>
        <h1 id="membership-page-title">让下一段路线，更从容。</h1>
        <p class="page-header__lead">额度、有效期和价格均由服务端确认，购买后以支付状态为准。</p>
      </div>
      <button
        class="refresh"
        type="button"
        :disabled="loading"
        :aria-label="loading ? '正在刷新会员计划' : '刷新会员计划列表'"
        @click="loadPlans"
      >
        <RefreshCw :size="17" :class="{ spin: loading }" />
        <span>刷新</span>
      </button>
    </header>

    <div v-if="loading" class="loading-block" role="status" aria-live="polite">
      <p class="state state--loading">
        <RefreshCw class="spin" :size="18" />
        <span>正在读取可购买计划...</span>
      </p>
      <ul class="skeleton-grid" aria-hidden="true">
        <li v-for="n in 3" :key="n" class="skeleton-plan"></li>
      </ul>
    </div>

    <section v-else-if="error" class="state state--error" role="alert">
      <CircleAlert :size="18" />
      <span>{{ error }}</span>
      <button type="button" @click="loadPlans">重新读取</button>
    </section>

    <section v-else class="plans" aria-label="可购买会员计划">
      <article
        v-for="(plan, index) in plans"
        :key="plan.id"
        class="plan reveal"
        :style="{ '--reveal-index': index }"
        :aria-label="`${plan.name}，${price(plan)}，有效期 ${plan.duration_days} 天`"
      >
        <div class="plan-main">
          <span class="plan-code">{{ plan.code }}</span>
          <h2>{{ plan.name }}</h2>
          <strong class="price">{{ price(plan) }} <small>/ {{ plan.duration_days }} 天</small></strong>
        </div>
        <ul>
          <li><Check :size="15" />{{ plan.generation_quota }} 次行程生成</li>
          <li><Check :size="15" />{{ plan.assistant_quota }} 次 AI 对话</li>
          <li><Check :size="15" />会员有效期 {{ plan.duration_days }} 天</li>
        </ul>
        <button
          class="buy"
          type="button"
          :disabled="!plan.purchasable || purchasing === plan.id"
          :aria-disabled="!plan.purchasable || purchasing === plan.id"
          @click="purchase(plan)"
        >
          <Sparkles :size="16" />{{ purchasing === plan.id ? '正在创建支付' : plan.purchasable ? '立即购买' : '暂不可购买' }}
        </button>
      </article>
      <p v-if="!plans.length" class="state state--empty">
        <CircleAlert :size="18" />
        <span>当前没有可购买的会员计划。</span>
      </p>
    </section>

    <RouterLink class="return-link" to="/me/access">查看我的权益</RouterLink>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.membership-page {
  color: var(--field-ink);
  margin: auto;
  max-width: 1060px;
  padding: 48px 24px 80px;
  position: relative;
}

/* ============ 滚动条美化 ============ */
.membership-page ::-webkit-scrollbar { width: 6px; }
.membership-page ::-webkit-scrollbar-track { background: transparent; }
.membership-page ::-webkit-scrollbar-thumb {
  background: var(--field-line);
  border-radius: 3px;
  transition: background 0.2s;
}
.membership-page ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

/* ============ 页头 ============ */
.page-header {
  align-items: flex-end;
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  display: flex;
  gap: 24px;
  justify-content: space-between;
  padding-bottom: 32px;
  animation: header-enter 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}

.page-header__intro { min-width: 0; }

.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.membership-page h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(38px, 6vw, 68px);
  font-weight: 600;
  line-height: 1.08;
  margin: 14px 0;
  letter-spacing: -0.01em;
}

.page-header__lead {
  color: var(--field-ink-soft);
  line-height: 1.65;
  margin: 0;
  max-width: 560px;
}

/* ============ 刷新按钮 ============ */
.refresh {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  font-weight: 700;
  font-size: 13px;
  justify-content: center;
  min-height: 42px;
  padding: 0 18px;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.refresh::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--field-teal);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 0;
}

.refresh > * { position: relative; z-index: 1; }

.refresh:hover:not(:disabled) {
  color: var(--field-white);
  border-color: var(--field-teal);
  box-shadow: 0 6px 20px rgba(8, 126, 120, 0.28);
  transform: scale(1.03);
}

.refresh:hover:not(:disabled)::before { transform: scaleX(1); }

.refresh:active:not(:disabled) { transform: scale(0.96); }

.refresh:disabled { cursor: not-allowed; opacity: 0.45; }

.refresh svg { transition: transform 0.3s ease; }
.refresh:hover:not(:disabled) svg { transform: rotate(180deg); }

/* ============ 状态条 ============ */
.state {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 10px;
  padding: 20px 24px;
  transition: all 0.25s ease;
}

.state--loading {
  color: var(--field-ink-soft);
  border-left: 3px solid var(--field-teal);
}

.state--error {
  border-color: var(--field-coral);
  border-left: 3px solid var(--field-coral);
  color: #9c4234;
  margin-top: 32px;
  animation: shake-in 0.4s ease;
}

@keyframes shake-in {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-6px); }
  40% { transform: translateX(4px); }
  60% { transform: translateX(-3px); }
  80% { transform: translateX(2px); }
}

.state--error button {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: inherit;
  cursor: pointer;
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
  min-height: 38px;
  padding: 0 16px;
  transition: all 0.2s ease;
}

.state--error button:hover {
  background: var(--field-coral);
  color: var(--field-white);
  transform: scale(1.03);
}

.state--error button:active { transform: scale(0.96); }

.state--empty {
  color: var(--field-muted);
  margin-top: 24px;
}

/* ============ 骨架屏 ============ */
.skeleton-grid {
  display: grid;
  gap: 16px;
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
}

.skeleton-plan {
  background: linear-gradient(90deg, var(--field-line) 25%, var(--field-paper) 50%, var(--field-line) 75%);
  background-size: 200% 100%;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  height: 120px;
  animation: shimmer 1.8s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ============ 计划列表 ============ */
.plans {
  display: grid;
  gap: 16px;
  margin-top: 36px;
}

/* ============ 计划卡片 ============ */
.plan {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 24px;
  grid-template-columns: 1.1fr 1fr auto;
  padding: 28px;
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.plan::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--field-teal), var(--field-coral));
  transform: scaleY(0);
  transform-origin: bottom;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.plan::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at top right, rgba(8, 126, 120, 0.04), transparent 60%);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.plan:hover {
  border-color: var(--field-teal);
  box-shadow: 0 12px 32px rgba(8, 126, 120, 0.10), 0 4px 12px rgba(19, 43, 58, 0.06);
  transform: translateY(-4px);
}

.plan:hover::before { transform: scaleY(1); transform-origin: top; }
.plan:hover::after { opacity: 1; }

.plan-main { min-width: 0; }

.plan-code {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.1em;
  display: inline-block;
  padding: 3px 8px;
  background: var(--field-teal-soft);
  border-radius: 4px;
  transition: all 0.2s ease;
}

.plan:hover .plan-code {
  background: var(--field-teal);
  color: var(--field-white);
}

.plan h2 {
  font-size: 24px;
  font-weight: 700;
  margin: 12px 0 8px;
  transition: color 0.2s ease;
}

.plan:hover h2 { color: var(--field-teal); }

.price {
  color: var(--field-coral);
  font-size: 30px;
  font-weight: 700;
  transition: transform 0.2s ease;
  display: inline-block;
}

.plan:hover .price { transform: scale(1.04); }

.price small {
  color: var(--field-muted);
  font: 700 12px var(--field-mono);
}

.plan ul {
  display: grid;
  gap: 12px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.plan li {
  align-items: center;
  color: var(--field-ink-soft);
  display: flex;
  gap: 8px;
  font-size: 13px;
  transition: transform 0.2s ease, color 0.2s ease;
}

.plan:hover li { transform: translateX(4px); }
.plan:hover li:nth-child(1) { transition-delay: 0s; }
.plan:hover li:nth-child(2) { transition-delay: 0.04s; }
.plan:hover li:nth-child(3) { transition-delay: 0.08s; }

.plan li svg {
  color: var(--field-coral);
  flex-shrink: 0;
  transition: transform 0.25s ease;
}

.plan:hover li svg { transform: scale(1.15) rotate(-5deg); }

/* ============ 购买按钮 ============ */
.buy {
  align-items: center;
  background: linear-gradient(135deg, var(--field-deep), #1a5263);
  border: none;
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  font-size: 14px;
  gap: 8px;
  justify-content: center;
  min-height: 44px;
  padding: 0 24px;
  position: relative;
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}

.buy::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--field-teal), #0aa39c);
  opacity: 0;
  transition: opacity 0.25s ease;
}

.buy > * { position: relative; z-index: 1; }

.buy:hover:not(:disabled) {
  transform: scale(1.04);
  box-shadow: 0 8px 24px rgba(8, 126, 120, 0.35), 0 2px 8px rgba(8, 126, 120, 0.2);
}

.buy:hover:not(:disabled)::before { opacity: 1; }

.buy:active:not(:disabled) {
  transform: scale(0.96);
  box-shadow: 0 2px 8px rgba(8, 126, 120, 0.2);
}

.buy:disabled {
  cursor: not-allowed;
  opacity: 0.4;
  background: var(--field-muted);
}

.buy svg { transition: transform 0.25s ease; }
.buy:hover:not(:disabled) svg { transform: rotate(15deg) scale(1.1); }

/* ============ 返回链接 ============ */
.return-link {
  color: var(--field-teal);
  display: inline-block;
  font-weight: 700;
  margin-top: 32px;
  padding: 4px 0;
  position: relative;
  text-decoration: none;
  transition: color 0.2s ease;
}

.return-link::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 0;
  height: 2px;
  background: var(--field-teal);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.return-link:hover {
  color: var(--field-deep);
}

.return-link:hover::after { width: 100%; }

/* ============ 入场动画 ============ */
.reveal {
  animation: reveal-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
  animation-delay: calc(var(--reveal-index, 0) * 80ms);
}

@keyframes reveal-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.spin { animation: spin 0.9s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* ============ 焦点光晕 ============ */
.refresh:focus-visible,
.buy:focus-visible,
.state--error button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(242, 163, 76, 0.4), 0 0 0 1px var(--field-saffron);
}

/* ============ 响应式 ============ */
@media (max-width: 700px) {
  .membership-page { padding: 32px 16px 58px; }
  .page-header { align-items: stretch; flex-direction: column; gap: 16px; }
  .refresh { width: 100%; }
  .plan { align-items: flex-start; grid-template-columns: 1fr; padding: 22px; }
  .skeleton-plan { height: 180px; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal { animation: none; }
  .skeleton-plan { animation: none; }
  .spin { animation: none; }
  .plan, .buy, .refresh, .return-link, .plan li, .plan li svg, .price, .plan-code, .plan h2 { transition: none; }
}
</style>
