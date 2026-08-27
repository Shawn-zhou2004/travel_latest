<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleAlert, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import qrcode from 'qrcode-generator'
import { RouterLink, useRoute } from 'vue-router'
import { useReveal } from '@/composables/useReveal'
import { normalizeApiError } from '@/services/api'
import { createMembershipQrPayment, getCurrentMembershipQrPayment, listMyMembershipPurchases, queryMembershipPurchasePayment, refreshMembershipQrPayment, type MembershipPurchase, type MembershipQrPayment } from './api'

const route = useRoute()
const root = ref<HTMLElement | null>(null)
useReveal(root)
const purchaseId = computed(() => typeof route.params.purchaseId === 'string' ? route.params.purchaseId : '')
const purchase = ref<MembershipPurchase | null>(null)
const payment = ref<MembershipQrPayment | null>(null)
const qrImage = ref('')
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const remainingSeconds = ref(0)
let pollTimer: number | undefined
let countdownTimer: number | undefined

const isFinal = computed(() => payment.value?.authorization_status === 'authorized' || ['paid', 'expired', 'closed', 'failed'].includes(payment.value?.status ?? ''))
const canRefresh = computed(() => ['expired', 'closed'].includes(payment.value?.status ?? ''))
const statusText = computed(() => {
  if (payment.value?.authorization_status === 'authorized') return '会员权益已开通'
  if (payment.value?.status === 'expired') return '二维码已过期'
  if (payment.value?.status === 'closed') return '支付已关闭'
  if (payment.value?.status === 'paid') return '支付成功，正在开通权益'
  if (payment.value?.status === 'failed') return '支付未完成'
  return '等待支付宝确认支付'
})
const countdownText = computed(() => `${String(Math.floor(remainingSeconds.value / 60)).padStart(2, '0')}:${String(remainingSeconds.value % 60).padStart(2, '0')}`)
const amount = computed(() => purchase.value ? `${purchase.value.currency === 'CNY' ? '¥' : purchase.value.currency}${Number(purchase.value.amount).toFixed(2)}` : '')

function stopPolling() { if (pollTimer !== undefined) { window.clearInterval(pollTimer); pollTimer = undefined } }
function stopCountdown() { if (countdownTimer !== undefined) { window.clearInterval(countdownTimer); countdownTimer = undefined } }
function stopTimers() { stopPolling(); stopCountdown() }
function updateCountdown() {
  const expiresAt = payment.value?.expires_at
  remainingSeconds.value = expiresAt ? Math.max(0, Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 1000)) : 0
  if (remainingSeconds.value === 0 && payment.value?.status && !isFinal.value) { stopTimers(); void refreshPaymentFacts() }
}
function startCountdown() { stopCountdown(); updateCountdown(); if (!isFinal.value && remainingSeconds.value > 0) countdownTimer = window.setInterval(updateCountdown, 1000) }
function startPolling() { stopPolling(); if (document.visibilityState !== 'visible' || isFinal.value) return; pollTimer = window.setInterval(() => void refreshPaymentFacts(), 3000) }
function applyPayment(next: MembershipQrPayment) { payment.value = { ...payment.value, ...next }; if (isFinal.value) stopTimers(); else { startCountdown(); startPolling() } }
async function refreshPaymentFacts() {
  if (!purchaseId.value || isFinal.value) return
  try { applyPayment(await queryMembershipPurchasePayment(purchaseId.value)); error.value = '' } catch (cause) { error.value = normalizeApiError(cause).message }
}
async function load() {
  if (!purchaseId.value) { error.value = '会员购买订单无效。'; loading.value = false; return }
  loading.value = true; error.value = ''
  try {
    const [purchases, current] = await Promise.all([listMyMembershipPurchases(), getCurrentMembershipQrPayment(purchaseId.value)])
    purchase.value = purchases.find((item) => item.id === purchaseId.value) ?? null
    if (!purchase.value) throw new Error('未找到该会员购买订单。')
    applyPayment(current.attempt_id || current.authorization_status === 'authorized' ? current : await createMembershipQrPayment(purchaseId.value))
  } catch (cause) { error.value = normalizeApiError(cause).message } finally { loading.value = false }
}
async function refreshQrCode() {
  if (!purchaseId.value || !canRefresh.value || refreshing.value) return
  refreshing.value = true; error.value = ''
  try { applyPayment(await refreshMembershipQrPayment(purchaseId.value)) } catch (cause) { error.value = normalizeApiError(cause).message } finally { refreshing.value = false }
}
function onVisibilityChange() { if (document.visibilityState === 'visible') { void refreshPaymentFacts(); startPolling() } else stopPolling() }
watch(() => payment.value?.qr_code, (code) => { if (!code) { qrImage.value = ''; return }; const renderer = qrcode(0, 'M'); renderer.addData(code); renderer.make(); qrImage.value = renderer.createDataURL(7, 0) }, { immediate: true })
onMounted(() => { document.addEventListener('visibilitychange', onVisibilityChange); void load() })
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', onVisibilityChange); stopTimers() })
</script>

<template>
  <main class="payment-page" :aria-busy="loading" ref="root">
    <header class="page-header">
      <p class="eyebrow">会员购买</p>
      <h1 id="payment-page-title">支付宝扫码支付</h1>
      <p class="page-header__lead">请使用支付宝扫描二维码完成支付，支付结果以服务端确认状态为准。</p>
    </header>

    <div v-if="loading" class="loading-block" role="status" aria-live="polite">
      <p class="state state--loading">
        <RefreshCw class="spin" :size="18" />
        <span>正在准备支付二维码...</span>
      </p>
      <div class="skeleton-card" aria-hidden="true">
        <div class="skeleton-line skeleton-line--lg shimmer"></div>
        <div class="skeleton-qr shimmer"></div>
        <div class="skeleton-line shimmer"></div>
      </div>
    </div>

    <section v-else-if="error && !payment" class="state state--error" role="alert">
      <CircleAlert :size="18" />
      <span>{{ error }}</span>
      <button type="button" @click="load">重新读取</button>
    </section>

    <section v-else-if="purchase && payment" class="payment-card reveal" aria-live="polite">
      <div class="details">
        <span class="plan-code">{{ purchase.plan_name }}</span>
        <strong>{{ amount }}</strong>
        <span>{{ purchase.duration_days }} 天会员有效期</span>
      </div>
      <div v-if="qrImage && !isFinal" class="qr-panel">
        <img :src="qrImage" alt="支付宝支付二维码" width="224" height="224">
        <p>请在 {{ countdownText }} 内完成扫码支付</p>
      </div>
      <div v-else class="result">
        <ShieldCheck :size="38" />
        <h2>{{ statusText }}</h2>
        <p v-if="payment.authorization_status !== 'authorized'">{{ canRefresh ? '请手动重新生成二维码后继续支付。' : '支付和权益状态正在由服务端核对。' }}</p>
      </div>
      <Transition name="fade">
        <p v-if="error" class="inline-error" role="alert">
          <CircleAlert :size="16" />{{ error }}
        </p>
      </Transition>
      <p class="status">
        <RefreshCw v-if="!isFinal" class="spin" :size="16" />{{ statusText }}
      </p>
      <button
        v-if="canRefresh"
        class="refresh"
        type="button"
        :disabled="refreshing"
        :aria-label="refreshing ? '正在重新生成二维码' : '重新生成二维码'"
        @click="refreshQrCode"
      >
        <RefreshCw :size="16" />{{ refreshing ? '正在生成' : '重新生成二维码' }}
      </button>
    </section>

    <nav class="page-nav" data-reveal aria-label="支付页面导航">
      <RouterLink to="/memberships">返回会员计划</RouterLink>
      <RouterLink to="/me/access">查看我的权益</RouterLink>
    </nav>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.payment-page {
  color: var(--field-ink);
  margin: auto;
  max-width: 780px;
  padding: 48px 24px 80px;
  position: relative;
}

/* ============ 滚动条美化 ============ */
.payment-page ::-webkit-scrollbar { width: 6px; }
.payment-page ::-webkit-scrollbar-track { background: transparent; }
.payment-page ::-webkit-scrollbar-thumb {
  background: var(--field-line);
  border-radius: 3px;
  transition: background var(--motion-fast) var(--ease-standard);
}
.payment-page ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

/* ============ 页头 ============ */
.page-header {
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  padding-bottom: 30px;
  animation: header-enter 0.6s var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}

.eyebrow,
.plan-code {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.payment-page h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(38px, 6vw, 62px);
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

/* ============ 状态条 ============ */
.state {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 10px;
  margin-top: 32px;
  padding: 20px 24px;
  transition: box-shadow var(--motion-base) var(--ease-standard);
}

.state--loading {
  color: var(--field-ink-soft);
  border-left: 3px solid var(--field-teal);
}

.state--error {
  border-color: var(--field-coral);
  border-left: 3px solid var(--field-coral);
  color: #9c4234;
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
  transition: background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.state--error button:hover {
  background: var(--field-coral);
  color: var(--field-white);
  transform: scale(1.03);
}

.state--error button:active { transform: scale(0.96); }

/* ============ 骨架屏 ============ */
.skeleton-card {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 24px;
  margin-top: 16px;
  padding: 28px;
  text-align: center;
}

.skeleton-line {
  border-radius: var(--travel-radius-sm);
  height: 16px;
  margin: 0 auto;
  width: 60%;
}

.skeleton-line--lg { height: 32px; width: 40%; }

.skeleton-qr {
  border-radius: var(--travel-radius);
  height: 224px;
  margin: 0 auto;
  width: 224px;
}

/* ============ 支付卡片 ============ */
.payment-card {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 24px;
  margin-top: 36px;
  padding: 32px;
  text-align: center;
  position: relative;
  overflow: hidden;
  transition: box-shadow var(--motion-slow) var(--ease-standard);
}

.payment-card:hover { box-shadow: var(--shadow-lift); }

.payment-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, var(--field-teal), var(--field-coral), var(--field-saffron));
}

.details {
  display: grid;
  gap: 8px;
}

.plan-code {
  display: inline-block;
  padding: 3px 10px;
  background: var(--field-teal-soft);
  border-radius: 4px;
  justify-self: center;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard);
}

.details strong {
  color: var(--field-coral);
  font-size: 36px;
  font-weight: 700;
  transition: transform var(--motion-fast) var(--ease-standard);
  display: inline-block;
}

.payment-card:hover .details strong { transform: scale(1.03); }

.details span:last-child {
  color: var(--field-muted);
  font-size: 13px;
}

/* ============ QR 面板 ============ */
.qr-panel {
  border-block: 1px solid var(--field-line);
  padding: 28px 0;
  position: relative;
}

.qr-panel img {
  display: block;
  height: 224px;
  margin: auto;
  max-width: 100%;
  width: 224px;
  border-radius: var(--travel-radius-sm);
  transition: box-shadow var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-out);
  animation: qr-enter 0.5s var(--ease-out) both;
}

@keyframes qr-enter {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

.qr-panel img:hover {
  transform: scale(1.03);
  box-shadow: 0 8px 24px rgba(8, 126, 120, 0.15);
}

.qr-panel p,
.result p {
  color: var(--field-muted);
  font-size: 13px;
  margin: 16px 0 0;
  transition: color var(--motion-fast) var(--ease-standard);
}

/* ============ 结果区 ============ */
.result {
  padding: 28px;
  animation: result-enter 0.4s var(--ease-out) both;
}

@keyframes result-enter {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.result svg {
  color: var(--field-teal);
  animation: icon-bounce 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55) both;
}

@keyframes icon-bounce {
  0% { opacity: 0; transform: scale(0); }
  60% { opacity: 1; transform: scale(1.15); }
  100% { transform: scale(1); }
}

.result h2 {
  font-size: 22px;
  font-weight: 700;
  margin: 14px 0 0;
}

/* ============ 状态文字 ============ */
.status {
  align-items: center;
  background: var(--field-paper);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  display: flex;
  font-size: 14px;
  gap: 8px;
  justify-content: center;
  margin: 0;
  padding: 12px 16px;
  transition: background-color var(--motion-fast) var(--ease-standard);
}

.inline-error {
  align-items: center;
  background: rgba(216, 110, 88, 0.08);
  border-radius: var(--travel-radius-sm);
  color: #9c4234;
  display: flex;
  font-size: 13px;
  gap: 6px;
  justify-content: center;
  margin: 0;
  padding: 10px 16px;
}

/* ============ 刷新按钮 ============ */
.refresh {
  align-items: center;
  background: var(--field-deep);
  border: none;
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  font-size: 14px;
  gap: 8px;
  justify-content: center;
  justify-self: center;
  min-height: 44px;
  padding: 0 24px;
  position: relative;
  overflow: hidden;
  transition: background-color var(--motion-base) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-base) var(--ease-standard),
    opacity var(--motion-fast) var(--ease-standard);
}

.refresh::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--field-teal);
  opacity: 0;
  transition: opacity var(--motion-base) var(--ease-standard);
}

.refresh > * { position: relative; z-index: 1; }

.refresh:hover:not(:disabled) {
  background: var(--field-teal);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(8, 126, 120, 0.28);
}

.refresh:hover:not(:disabled)::before { opacity: 0; }

.refresh:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  box-shadow: 0 2px 8px rgba(8, 126, 120, 0.2);
}

.refresh:disabled { cursor: not-allowed; opacity: 0.4; }

.refresh svg { transition: transform var(--motion-base) var(--ease-out); }
.refresh:hover:not(:disabled) svg { transform: rotate(120deg); }

/* ============ 导航链接 ============ */
.page-nav {
  display: flex;
  gap: 24px;
  justify-content: center;
  margin-top: 32px;
}

.page-nav a {
  color: var(--field-teal);
  font-weight: 700;
  font-size: 14px;
  padding: 6px 0;
  position: relative;
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.page-nav a::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 0;
  height: 2px;
  background: var(--field-teal);
  transition: width var(--motion-base) var(--ease-out);
}

.page-nav a:hover { color: var(--field-deep); transform: translateY(-1px); }
.page-nav a:hover::after { width: 100%; }
.page-nav a:active { transform: translateY(0) scale(0.98); }

/* ============ 入场动画 ============ */
.reveal {
  animation: reveal-up var(--motion-slow) var(--ease-out) both;
}

@keyframes reveal-up {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

.spin { animation: spin 0.9s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* ============ 焦点光晕 ============ */
.refresh:focus-visible,
.state--error button:focus-visible,
.page-nav a:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus), 0 0 0 1px var(--field-saffron);
}

/* ============ 响应式 ============ */
@media (max-width: 700px) {
  .payment-page { padding: 32px 16px 58px; }
  .page-nav { flex-direction: column; gap: 12px; }
  .payment-card { padding: 22px; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal { animation: none; }
  .skeleton-line, .skeleton-qr { animation: none; }
  .spin { animation: none; }
  .qr-panel img { animation: none; }
  .result svg { animation: none; }
  .result { animation: none; }
  .payment-card, .refresh, .page-nav a, .page-nav a::after, .details strong, .plan-code, .qr-panel img, .status, .state { transition: none; }
  .page-header { animation: none; }
}
</style>
