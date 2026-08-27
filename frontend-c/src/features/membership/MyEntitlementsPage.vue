<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CircleAlert, RefreshCw } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { listMyMembershipPurchases, type MembershipPurchase } from './api'
import { getMyAIEntitlements, type AIEntitlements } from '@/features/ai/assistantApi'
import { normalizeApiError } from '@/services/api'
const balances = ref<AIEntitlements | null>(null); const purchases = ref<MembershipPurchase[]>([]); const loading = ref(true); const error = ref('')
const date = (value: string | null) => value ? new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) : '尚未确认'
const money = (value: string|number, currency: string) => `${currency === 'CNY' ? '¥' : currency}${Number(value).toFixed(2)}`
const status = (value: string) => ({pending_payment:'待支付',paid:'已支付',authorized:'已开通',pending:'处理中',failed:'失败'}[value] ?? value)
async function load() { loading.value=true; error.value=''; try { [balances.value,purchases.value] = await Promise.all([getMyAIEntitlements(),listMyMembershipPurchases()]) } catch(cause) { error.value=normalizeApiError(cause).message } finally { loading.value=false } }
onMounted(() => { void load() })
</script>

<template>
  <main class="access-page" :aria-busy="loading">
    <header class="page-header">
      <div class="page-header__intro">
        <p class="eyebrow">账户权益</p>
        <h1 id="access-page-title">我的会员与额度</h1>
        <p class="page-header__lead">查看会员有效期、免费额度和最近购买记录。</p>
      </div>
      <button
        class="refresh"
        type="button"
        :disabled="loading"
        :aria-label="loading ? '正在刷新权益' : '刷新会员与额度'"
        @click="load"
      >
        <RefreshCw :size="17" :class="{ spin: loading }" />
        <span>刷新</span>
      </button>
    </header>

    <div v-if="loading" class="loading-block" role="status" aria-live="polite">
      <p class="state state--loading">
        <RefreshCw class="spin" :size="18" />
        <span>正在读取权益...</span>
      </p>
      <div class="skeleton-grid" aria-hidden="true">
        <div v-for="n in 3" :key="n" class="skeleton-card"></div>
      </div>
    </div>

    <section v-else-if="error" class="state state--error" role="alert">
      <CircleAlert :size="18" />
      <span>{{ error }}</span>
      <button type="button" @click="load">重新读取</button>
    </section>

    <template v-else-if="balances">
      <section class="balance-grid" aria-label="额度概览">
        <article class="balance-card reveal" style="--reveal-index: 0">
          <span class="balance-card__label">免费额度 · 本自然月</span>
          <div class="quota">
            <strong>{{ balances.free.itinerary_generation_remaining }} 次</strong>
            <small>行程生成 · 截止 {{ date(balances.free.period_end) }}</small>
          </div>
          <div class="quota">
            <strong>{{ balances.free.assistant_message_remaining }} 次</strong>
            <small>AI 对话</small>
          </div>
        </article>
        <article v-if="balances.membership" class="balance-card reveal" style="--reveal-index: 1">
          <span class="balance-card__label">当前会员额度</span>
          <div class="quota">
            <strong>{{ balances.membership.itinerary_generation_remaining }} 次</strong>
            <small>行程生成</small>
          </div>
          <div class="quota">
            <strong>{{ balances.membership.assistant_message_remaining }} 次</strong>
            <small>AI 对话 · 有效至 {{ date(balances.membership.period_end) }}</small>
          </div>
        </article>
        <article v-else class="balance-card balance-card--upgrade reveal" style="--reveal-index: 1">
          <span class="balance-card__label">还没有有效会员</span>
          <strong class="upgrade-title">需要更多 AI 额度？</strong>
          <RouterLink class="upgrade-link" to="/memberships">查看会员计划</RouterLink>
        </article>
      </section>

      <section class="purchases" aria-label="最近购买记录">
        <h2>最近购买</h2>
        <p v-if="!purchases.length" class="state state--empty">
          <CircleAlert :size="18" />
          <span>还没有购买记录。</span>
        </p>
        <article
          v-for="(purchase, index) in purchases"
          :key="purchase.id"
          class="purchase-row reveal"
          :style="{ '--reveal-index': index }"
        >
          <div class="purchase-row__main">
            <strong>{{ purchase.plan_name }}</strong>
            <span>{{ money(purchase.amount, purchase.currency) }} · {{ purchase.duration_days }} 天</span>
          </div>
          <div class="purchase-row__meta">
            <span class="purchase-status" :data-status="purchase.payment_status">{{ status(purchase.payment_status) }} / {{ status(purchase.authorization_status) }}</span>
            <small>{{ purchase.valid_until ? `有效至 ${date(purchase.valid_until)}` : `创建于 ${date(purchase.created_at)}` }}</small>
          </div>
        </article>
      </section>
    </template>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.access-page {
  color: var(--field-ink);
  margin: auto;
  max-width: 1000px;
  padding: 48px 24px 80px;
  position: relative;
}

/* ============ 滚动条美化 ============ */
.access-page ::-webkit-scrollbar { width: 6px; }
.access-page ::-webkit-scrollbar-track { background: transparent; }
.access-page ::-webkit-scrollbar-thumb {
  background: var(--field-line);
  border-radius: 3px;
  transition: background 0.2s;
}
.access-page ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

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

.access-page h1 {
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
  max-width: 520px;
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
  font-weight: 700;
  font-size: 13px;
  gap: 8px;
  justify-content: center;
  min-height: 42px;
  padding: 0 18px;
  position: relative;
  overflow: hidden;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
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
.state--empty { color: var(--field-muted); margin-top: 16px; }

/* ============ 骨架屏 ============ */
.skeleton-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 16px;
}

.skeleton-card {
  background: linear-gradient(90deg, var(--field-line) 25%, var(--field-paper) 50%, var(--field-line) 75%);
  background-size: 200% 100%;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  height: 168px;
  animation: shimmer 1.8s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ============ 额度卡片网格 ============ */
.balance-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 36px;
}

.balance-card {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 18px;
  padding: 28px;
  position: relative;
  overflow: hidden;
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}

.balance-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--field-teal), var(--field-coral));
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.balance-card::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at top right, rgba(8, 126, 120, 0.03), transparent 60%);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.balance-card:hover {
  border-color: var(--field-teal);
  box-shadow: 0 12px 32px rgba(8, 126, 120, 0.10), 0 4px 12px rgba(19, 43, 58, 0.06);
  transform: translateY(-4px);
}

.balance-card:hover::before { transform: scaleX(1); }
.balance-card:hover::after { opacity: 1; }

.balance-card__label {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  transition: all 0.2s ease;
}

.balance-card:hover .balance-card__label {
  color: var(--field-deep);
}

.quota {
  display: grid;
  gap: 6px;
  transition: transform 0.2s ease;
}

.balance-card:hover .quota { transform: translateX(3px); }

.balance-card strong {
  font-size: 28px;
  font-weight: 700;
  transition: color 0.2s ease;
}

.balance-card:hover strong { color: var(--field-teal); }

.balance-card small {
  color: var(--field-muted);
  font-size: 12px;
}

/* ============ 升级卡片 ============ */
.balance-card--upgrade {
  background: linear-gradient(135deg, var(--field-teal-soft), var(--field-paper));
  border-color: var(--field-teal-soft);
}

.balance-card--upgrade::before {
  background: linear-gradient(90deg, var(--field-saffron), var(--field-coral));
}

.balance-card--upgrade:hover {
  border-color: var(--field-saffron);
  box-shadow: 0 12px 32px rgba(242, 163, 76, 0.15);
}

.upgrade-title {
  font-size: 20px;
  font-weight: 700;
}

.upgrade-link {
  color: var(--field-coral);
  font-weight: 800;
  padding: 4px 0;
  position: relative;
  text-decoration: none;
  transition: all 0.2s ease;
}

.upgrade-link::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 0;
  height: 2px;
  background: var(--field-coral);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.upgrade-link:hover {
  color: var(--field-deep);
  transform: translateX(3px);
}

.upgrade-link:hover::after { width: 100%; }

/* ============ 购买记录 ============ */
.purchases {
  margin-top: 44px;
}

.purchases h2 {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 12px;
  position: relative;
  padding-left: 14px;
}

.purchases h2::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 20px;
  background: var(--field-teal);
  border-radius: 2px;
}

.purchase-row {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 18px 22px;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.purchase-row::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--field-teal);
  transform: scaleY(0);
  transition: transform 0.25s ease;
}

.purchase-row:hover {
  border-color: var(--field-teal);
  box-shadow: 0 6px 20px rgba(19, 43, 58, 0.06);
  transform: translateX(4px);
}

.purchase-row:hover::before { transform: scaleY(1); }

.purchase-row__main {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.purchase-row__main strong {
  font-size: 16px;
  font-weight: 700;
  transition: color 0.2s ease;
}

.purchase-row:hover .purchase-row__main strong { color: var(--field-teal); }

.purchase-row__main span {
  color: var(--field-muted);
  font-size: 13px;
}

.purchase-row__meta {
  display: grid;
  gap: 5px;
  text-align: right;
}

.purchase-status {
  color: var(--field-teal);
  font: 700 12px var(--field-mono);
  letter-spacing: 0.04em;
  display: inline-block;
  padding: 3px 8px;
  background: var(--field-teal-soft);
  border-radius: 4px;
  transition: all 0.2s ease;
}

.purchase-status[data-status="failed"] {
  color: var(--field-coral);
  background: rgba(216, 110, 88, 0.1);
}

.purchase-status[data-status="pending_payment"] {
  color: var(--field-saffron);
  background: rgba(242, 163, 76, 0.12);
}

.purchase-row__meta small {
  color: var(--field-muted);
  font-size: 12px;
}

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
.state--error button:focus-visible,
.upgrade-link:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(242, 163, 76, 0.4), 0 0 0 1px var(--field-saffron);
}

/* ============ 响应式 ============ */
@media (max-width: 700px) {
  .access-page { padding: 32px 16px 58px; }
  .page-header { align-items: stretch; flex-direction: column; gap: 16px; }
  .refresh { width: 100%; }
  .skeleton-grid { grid-template-columns: 1fr; }
  .balance-grid { grid-template-columns: 1fr; }
  .purchase-row { align-items: flex-start; flex-direction: column; gap: 10px; }
  .purchase-row__meta { text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal { animation: none; }
  .skeleton-card { animation: none; }
  .spin { animation: none; }
  .balance-card, .purchase-row, .refresh, .upgrade-link, .purchase-status, .balance-card strong, .purchase-row__main strong { transition: none; }
}
</style>
