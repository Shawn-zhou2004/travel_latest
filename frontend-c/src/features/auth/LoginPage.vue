<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { ApiError } from '@/services/api'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const phone = ref('')
const code = ref('')
const password = ref('')
const debugCode = ref('')
const error = ref('')
const mode = ref<'sms' | 'password'>('sms')
const sent = ref(false)
const sending = ref(false)
const countdown = ref(0)
let timer: number | undefined

const canSend = computed(() => /^1[3-9]\d{9}$/.test(phone.value) && countdown.value === 0)
const canLogin = computed(() => {
  const validPhone = /^1[3-9]\d{9}$/.test(phone.value)
  if (mode.value === 'sms') return /^\d{4,6}$/.test(code.value) && validPhone
  return password.value.length >= 8 && validPhone
})

const sendErrorMessages: Record<string, string> = {
  SMS_THROTTLED: '发送过于频繁，请稍后再试。',
  SMS_SEND_FAILED: '验证码发送失败，请稍后重试。',
}

const loginErrorMessages: Record<string, string> = {
  INVALID_SMS_CODE: '验证码错误或已过期，请重试。',
  INVALID_CREDENTIALS: '手机号或密码不正确。',
  PASSWORD_NOT_SET: '该账号尚未设置密码，请使用短信验证码登录。',
  PHONE_NOT_REGISTERED: '该手机号还未注册，请先注册。',
}

function errorCode(reason: unknown): string {
  return (reason as Partial<ApiError> | null)?.code ?? ''
}

async function requestCode() {
  if (!canSend.value) return
  error.value = ''
  sending.value = true
  try {
    const response = await auth.sendCode(phone.value)
    debugCode.value = response.debug_code ?? ''
    sent.value = true
    countdown.value = response.expires_in > 60 ? 60 : response.expires_in
    timer = window.setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0 && timer) window.clearInterval(timer)
    }, 1000)
  } catch (reason) {
    error.value = sendErrorMessages[errorCode(reason)] ?? '验证码发送失败，请稍后重试。'
  } finally {
    sending.value = false
  }
}

async function login() {
  if (!canLogin.value) return
  error.value = ''
  try {
    if (mode.value === 'sms') await auth.login(phone.value, code.value)
    else await auth.loginWithPassword(phone.value, password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect.startsWith('/') ? redirect : '/')
  } catch (reason) {
    error.value = loginErrorMessages[errorCode(reason)] ?? '登录失败，请稍后重试。'
  }
}

function switchMode(next: 'sms' | 'password') {
  mode.value = next
  error.value = ''
}

const showRegisterHint = computed(() => error.value === loginErrorMessages.PHONE_NOT_REGISTERED)
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="brand-mark">TRAVEL / C</div>
      <p class="eyebrow">Your plans, in one place</p>
      <h1>登录以继续</h1>
      <p class="intro">用手机号打开已保存的行程、对话与订单。</p>
      <div class="mode-tabs" role="tablist" aria-label="登录方式">
        <button class="mode-tab" :class="{ active: mode === 'sms' }" type="button" role="tab" :aria-selected="mode === 'sms'" @click="switchMode('sms')">短信登录</button>
        <button class="mode-tab" :class="{ active: mode === 'password' }" type="button" role="tab" :aria-selected="mode === 'password'" @click="switchMode('password')">密码登录</button>
      </div>
      <form @submit.prevent="login">
        <label class="field">手机号<input v-model="phone" inputmode="tel" autocomplete="tel" maxlength="11" placeholder="13800000000" /></label>
        <div v-if="mode === 'sms'" class="code-row">
          <label class="field">验证码<input v-model="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="短信验证码" /></label>
          <button class="secondary" type="button" :disabled="!canSend || sending" @click="requestCode">
            <span v-if="sending" class="spin-mini" aria-hidden="true"></span>{{ sending ? '发送中' : countdown ? `${countdown}s` : sent ? '重新发送' : '获取验证码' }}
          </button>
        </div>
        <label v-else class="field">密码<input v-model="password" type="password" autocomplete="current-password" minlength="8" maxlength="64" placeholder="至少 8 位密码" /></label>
        <Transition name="slide-down">
          <p v-if="debugCode" class="debug-code">开发环境验证码：<strong>{{ debugCode }}</strong></p>
        </Transition>
        <Transition name="slide-down">
          <p v-if="error" class="error" role="alert">{{ error }}<RouterLink v-if="showRegisterHint" class="error-link" :to="{ path: '/register', query: { phone: phone } }">去注册</RouterLink></p>
        </Transition>
        <button class="primary" type="submit" :disabled="!canLogin || auth.busy">
          <span v-if="auth.busy" class="spin-mini" aria-hidden="true"></span>{{ auth.busy ? '登录中' : '登录' }}
        </button>
      </form>
      <p class="register-hint">还没有账号？<RouterLink class="register-link" to="/register">立即注册</RouterLink></p>
      <p class="legal">继续即表示你同意以负责任的方式使用本开发环境。</p>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  align-items: center;
  background: linear-gradient(145deg, color-mix(in srgb, var(--field-teal-soft) 82%, var(--field-white)), color-mix(in srgb, var(--field-white) 88%, var(--field-saffron)));
  color: var(--field-ink);
  display: grid;
  min-height: calc(100vh - 64px);
  padding: 32px 18px;
  position: relative;
  overflow: hidden;
}
.login-page::before {
  border: 1px solid color-mix(in srgb, var(--field-teal) 22%, transparent);
  border-radius: 50%;
  content: '';
  height: min(56vw, 580px);
  position: absolute;
  right: -18vw;
  top: -25vw;
  width: min(56vw, 580px);
  animation: drift 18s ease-in-out infinite alternate;
}
@keyframes drift { from { transform: translate(0, 0); } to { transform: translate(-12px, 10px); } }

.login-panel {
  animation: panel-enter var(--motion-slow) var(--ease-out) both;
  background: var(--field-white);
  border: 1px solid color-mix(in srgb, var(--field-line) 70%, var(--field-teal));
  border-radius: 14px;
  box-shadow: 0 22px 58px color-mix(in srgb, var(--field-deep) 13%, transparent);
  margin: 0 auto;
  max-width: 500px;
  padding: 42px;
  position: relative;
  width: 100%;
}
.login-panel::before {
  background: var(--field-saffron);
  border-radius: 7px 7px 0 0;
  content: '';
  height: 6px;
  left: 0;
  position: absolute;
  right: 0;
  top: 0;
}
@keyframes panel-enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }

.brand-mark {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  display: inline-block;
  font: 800 12px var(--field-mono);
  letter-spacing: .12em;
  padding: 6px 10px;
}
.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: .12em;
  margin: 38px 0 10px;
  text-transform: uppercase;
}
.login-panel h1 { font-size: 40px; letter-spacing: 0; line-height: 1.05; margin: 0; }
.intro { color: var(--field-ink-soft); font-size: 15px; line-height: 1.6; margin: 14px 0 24px; }

.mode-tabs {
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 22px;
  margin: 0 0 22px;
}
.mode-tab {
  background: none;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--field-ink-soft);
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  min-height: 40px;
  padding: 8px 2px;
}
.mode-tab.active { border-bottom-color: var(--field-teal); color: var(--field-teal); }
.mode-tab:focus-visible { outline: 2px solid var(--field-teal); outline-offset: 2px; }

form { display: grid; gap: 17px; }
.field { color: var(--field-ink); display: grid; font-size: 13px; font-weight: 700; gap: 7px; }
.field input {
  background: var(--field-paper);
  border: 1px solid var(--field-line);
  border-radius: 7px;
  box-sizing: border-box;
  color: var(--field-ink);
  font: inherit;
  font-weight: 400;
  min-height: 48px;
  padding: 10px 14px;
  transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard), background-color var(--motion-fast) var(--ease-standard);
  width: 100%;
}
.field input::placeholder { color: var(--field-muted); }
.field input:hover { border-color: color-mix(in srgb, var(--field-teal) 50%, var(--field-line)); }
.field input:focus-visible { border-color: var(--field-teal); box-shadow: 0 0 0 3px var(--field-teal-soft); outline: 0; }

.code-row { align-items: end; display: grid; gap: 10px; grid-template-columns: 1fr auto; }
.code-row .field { min-width: 0; }

button { border: 0; cursor: pointer; font: inherit; font-weight: 800; min-height: 48px; padding: 10px 16px; }
button:disabled { cursor: not-allowed; opacity: .5; }
.primary {
  background: var(--field-deep);
  border-radius: 7px;
  box-shadow: 0 9px 18px color-mix(in srgb, var(--field-deep) 18%, transparent);
  color: var(--field-white);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
  width: 100%;
}
.primary:hover:not(:disabled) { background: var(--field-teal); transform: translateY(-1px); box-shadow: 0 12px 24px color-mix(in srgb, var(--field-teal) 28%, transparent); }
.primary:active:not(:disabled) { transform: translateY(0) scale(0.98); }
.secondary {
  background: var(--field-white);
  border: 1px solid var(--field-teal);
  border-radius: 7px;
  color: var(--field-teal);
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard);
}
.secondary:hover:not(:disabled) { background: var(--field-teal); color: var(--field-white); transform: translateY(-1px); }
.secondary:active:not(:disabled) { transform: scale(0.97); }

.spin-mini {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  display: inline-block;
  animation: spin 0.7s linear infinite;
}

.debug-code {
  background: color-mix(in srgb, var(--field-saffron) 18%, var(--field-white));
  border-left: 3px solid var(--field-saffron);
  border-radius: 4px;
  color: #854d0e;
  font: 13px var(--field-mono);
  margin: -4px 0 0;
  padding: 10px 12px;
}
.debug-code strong { font-weight: 800; }
.error {
  align-items: center;
  background: color-mix(in srgb, var(--field-coral) 12%, var(--field-white));
  border-left: 3px solid var(--field-coral);
  border-radius: 4px;
  color: #9c4234;
  display: flex;
  font-size: 13px;
  gap: 8px;
  margin: -4px 0 0;
  padding: 10px 12px;
}
.error-link { color: inherit; font-weight: 800; text-decoration: underline; }
.register-hint { color: var(--field-ink-soft); font-size: 14px; margin: 18px 0 0; }
.register-link { color: var(--field-teal); font-weight: 800; }
.legal { color: var(--field-muted); font-size: 12px; line-height: 1.5; margin: 24px 0 0; }

@media (max-width: 520px) {
  .login-panel { border-radius: 10px; padding: 34px 22px; }
  .login-panel h1 { font-size: 32px; }
  .code-row { grid-template-columns: 1fr; }
  .secondary { width: 100%; justify-content: center; }
}

@media (prefers-reduced-motion: reduce) {
  .login-page::before, .login-panel, .spin-mini { animation: none; }
  .field input, .primary, .secondary { transition: none; transform: none; }
}
</style>
