<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { ApiError } from '@/services/api'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const phone = ref('')
const code = ref('')
const nickname = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const sent = ref(false)
const sending = ref(false)
const countdown = ref(0)
let timer: number | undefined

onMounted(() => {
  const fromQuery = typeof route.query.phone === 'string' ? route.query.phone : ''
  if (/^1[3-9]\d{9}$/.test(fromQuery)) phone.value = fromQuery
})

const canSend = computed(() => /^1[3-9]\d{9}$/.test(phone.value) && countdown.value === 0)
const canSubmit = computed(
  () =>
    /^1[3-9]\d{9}$/.test(phone.value) &&
    /^\d{4,6}$/.test(code.value) &&
    nickname.value.trim().length >= 1 &&
    password.value.length >= 8 &&
    password.value === confirmPassword.value,
)

const sendErrorMessages: Record<string, string> = {
  SMS_THROTTLED: '发送过于频繁，请稍后再试。',
  SMS_SEND_FAILED: '验证码发送失败，请稍后重试。',
}

const registerErrorMessages: Record<string, string> = {
  INVALID_SMS_CODE: '验证码错误或已过期，请重试。',
  PHONE_ALREADY_REGISTERED: '该手机号已注册，请直接登录。',
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

async function submit() {
  if (!canSubmit.value) return
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致。'
    return
  }
  error.value = ''
  try {
    await auth.register(phone.value, code.value, nickname.value.trim(), password.value)
    await router.replace('/')
  } catch (reason) {
    error.value = registerErrorMessages[errorCode(reason)] ?? '注册失败，请稍后重试。'
  }
}
</script>

<template>
  <main class="register-page">
    <section class="register-panel">
      <div class="brand-mark">TRAVEL / C</div>
      <p class="eyebrow">Join the journey</p>
      <h1>创建账号</h1>
      <p class="intro">验证手机号并设置密码，注册后自动登录。</p>
      <form @submit.prevent="submit">
        <label class="field">用户名<input v-model="nickname" maxlength="64" autocomplete="nickname" placeholder="怎么称呼你" /></label>
        <label class="field">手机号<input v-model="phone" inputmode="tel" autocomplete="tel" maxlength="11" placeholder="13800000000" /></label>
        <div class="code-row">
          <label class="field">验证码<input v-model="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="短信验证码" /></label>
          <button class="secondary" type="button" :disabled="!canSend || sending" @click="requestCode">
            <span v-if="sending" class="spin-mini" aria-hidden="true"></span>{{ sending ? '发送中' : countdown ? `${countdown}s` : sent ? '重新发送' : '获取验证码' }}
          </button>
        </div>
        <label class="field">密码<input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="64" placeholder="至少 8 位密码" /></label>
        <label class="field">确认密码<input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" maxlength="64" placeholder="再次输入密码" /></label>
        <Transition name="slide-down">
          <p v-if="error" class="error" role="alert">{{ error }}</p>
        </Transition>
        <button class="primary" type="submit" :disabled="!canSubmit || auth.busy">
          <span v-if="auth.busy" class="spin-mini" aria-hidden="true"></span>{{ auth.busy ? '注册中' : '注册并登录' }}
        </button>
      </form>
      <p class="login-hint">已有账号？<RouterLink class="login-link" to="/login">直接登录</RouterLink></p>
      <p class="legal">继续即表示你同意以负责任的方式使用本开发环境。</p>
    </section>
  </main>
</template>

<style scoped>
.register-page {
  align-items: center;
  background: linear-gradient(145deg, color-mix(in srgb, var(--field-teal-soft) 82%, var(--field-white)), color-mix(in srgb, var(--field-white) 88%, var(--field-saffron)));
  color: var(--field-ink);
  display: grid;
  min-height: calc(100vh - 64px);
  padding: 32px 18px;
  position: relative;
  overflow: hidden;
}
.register-page::before {
  border: 1px solid color-mix(in srgb, var(--field-teal) 22%, transparent);
  border-radius: 50%;
  content: '';
  height: min(56vw, 580px);
  position: absolute;
  left: -18vw;
  bottom: -25vw;
  width: min(56vw, 580px);
  animation: drift 18s ease-in-out infinite alternate;
}
@keyframes drift { from { transform: translate(0, 0); } to { transform: translate(12px, -10px); } }

.register-panel {
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
.register-panel::before {
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
.register-panel h1 { font-size: 40px; letter-spacing: 0; line-height: 1.05; margin: 0; }
.intro { color: var(--field-ink-soft); font-size: 15px; line-height: 1.6; margin: 14px 0 28px; }

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
.login-hint { color: var(--field-ink-soft); font-size: 14px; margin: 18px 0 0; }
.login-link { color: var(--field-teal); font-weight: 800; }
.legal { color: var(--field-muted); font-size: 12px; line-height: 1.5; margin: 24px 0 0; }

@media (max-width: 520px) {
  .register-panel { border-radius: 10px; padding: 34px 22px; }
  .register-panel h1 { font-size: 32px; }
  .code-row { grid-template-columns: 1fr; }
  .secondary { width: 100%; justify-content: center; }
}

@media (prefers-reduced-motion: reduce) {
  .register-page::before, .register-panel, .spin-mini { animation: none; }
  .field input, .primary, .secondary { transition: none; transform: none; }
}
</style>
