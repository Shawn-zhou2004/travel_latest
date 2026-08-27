<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const canLogin = computed(() => username.value.trim().length >= 1 && password.value.length >= 1)

async function login() {
  if (!canLogin.value) return
  error.value = ''
  try { await auth.login(username.value.trim(), password.value); await router.replace(typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : auth.isProviderSession ? '/provider/experiences' : '/') }
  catch (reason) { error.value = reason instanceof Error ? reason.message : 'The administrator account could not be signed in.' }
}
</script>

<template>
  <main class="login-page"><section class="login-panel"><div class="brand-mark">TRAVEL / B</div><p class="eyebrow">Operations workspace</p><h1>Sign in to administration</h1><p class="intro">Fixed backoffice account: sign in with the configured username and password.</p><form @submit.prevent="login"><label>Username<input v-model="username" autocomplete="username" maxlength="64" placeholder="admin" /></label><label>Password<input v-model="password" type="password" autocomplete="current-password" maxlength="64" placeholder="Password" /></label><p v-if="error" class="error" role="alert">{{ error }}</p><button class="primary" type="submit" :disabled="!canLogin || auth.busy">{{ auth.busy ? 'Signing in' : 'Enter console' }}</button></form></section></main>
</template>

<style scoped>.login-page{align-items:center;background:#e9eef3;color:#172033;display:grid;min-height:calc(100vh - 64px);padding:32px 18px}.login-panel{background:#fff;box-shadow:0 20px 60px rgba(20,33,61,.12);margin:auto;max-width:500px;padding:34px;width:100%}.brand-mark{color:#14213d;font:800 12px ui-monospace,monospace;letter-spacing:.12em}.eyebrow{color:#0c4a6e;font:700 12px ui-monospace,monospace;margin:38px 0 10px;text-transform:uppercase}h1{font-size:36px;line-height:1.08;margin:0}.intro{color:#526076;line-height:1.6;margin:14px 0 28px}form{display:grid;gap:17px}label{color:#26384a;display:grid;font-size:13px;font-weight:700;gap:7px}input{border:1px solid #b7c6cf;box-sizing:border-box;font:inherit;min-height:46px;padding:10px 12px;width:100%}input:focus-visible,button:focus-visible{outline:3px solid #f59e0b;outline-offset:3px}button{border:0;cursor:pointer;font:inherit;font-weight:800;min-height:46px;padding:10px 16px}button:disabled{cursor:default;opacity:.5}.primary{background:#14213d;color:#fff;width:100%}.error{color:#b42318;font-size:13px;margin:-4px 0 0}@media(max-width:520px){.login-panel{padding:26px 20px}h1{font-size:32px}}</style>
