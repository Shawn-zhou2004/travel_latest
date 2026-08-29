import { api } from '@/services/api'
import { clearSession, getAccessToken } from '@/services/session'
import { refreshAccessToken } from '@/services/api'
import { newClientId } from '@/services/id'

export interface AiConversation { id: string; title: string | null; created_at: string; updated_at: string }
export interface AiCitation { document_id: string; chunk_id: string; source_type: string; source_id: string; source_host?: string; city_code: string; content: string }
export interface AiMessage { id: string; role: 'user' | 'assistant' | 'system' | 'tool'; content: { text?: string; citations?: AiCitation[]; kind?: 'source_backed' | 'live_web' | 'clarification' }; client_message_id: string | null; created_at: string }
export interface AiMemory { id: string; memory_type: 'profile' | 'episodic'; memory_key: string; memory_value: Record<string, unknown>; source: string; confidence: number; created_at: string; updated_at: string }
export interface AIEntitlementBalance { source: 'free' | 'membership'; itinerary_generation_remaining: number; assistant_message_remaining: number; period_end: string }
export interface AIEntitlements { free: AIEntitlementBalance; membership: AIEntitlementBalance | null }

export async function listAiConversations() { const { data } = await api.get<{ items: AiConversation[] }>('/ai/conversations'); return data.items }
export async function createAiConversation(title?: string) { const { data } = await api.post<AiConversation>('/ai/conversations', { title }); return data }
export async function deleteAiConversation(conversationId: string) { await api.delete(`/ai/conversations/${conversationId}`) }
export async function listAiMessages(conversationId: string) { const { data } = await api.get<{ items: AiMessage[] }>(`/ai/conversations/${conversationId}/messages`); return data.items }
export async function askAiAssistant(conversationId: string, body: { text: string; client_message_id: string }) { const { data } = await api.post<{ user_message: AiMessage; assistant_message: AiMessage }>(`/ai/conversations/${conversationId}:ask`, body); return data }
export async function getMyAIEntitlements() { const { data } = await api.get<AIEntitlements>('/users/me/ai-entitlements'); return data }

export type AiAssistantStreamEvent =
  | { type: 'progress'; runId: string; phase: string; message: string }
  | { type: 'delta'; runId: string; text: string }
  | { type: 'completed'; runId: string; message: AiMessage }
  | { type: 'failed'; runId: string; code?: string; message: string }

export async function streamAiAssistant(
  conversationId: string,
  body: { text: string; client_message_id: string },
  onEvent: (event: AiAssistantStreamEvent) => void,
) {
  await consumeSse(`/ai/conversations/${conversationId}:ask-stream`, { method: 'POST', body: JSON.stringify(body) }, onEvent)
}

export async function replayAiAssistantRun(runId: string, onEvent: (event: AiAssistantStreamEvent) => void) {
  await consumeSse(`/ai/assistant-runs/${runId}/events`, { method: 'GET' }, onEvent)
}

async function consumeSse(path: string, init: RequestInit, onEvent: (event: AiAssistantStreamEvent) => void) {
  let response = await fetchSse(path, init)
  if (response.status === 401 && getAccessToken()) {
    const refreshed = await refreshAccessToken('/api/v1')
    if (refreshed) response = await fetchSse(path, init)
    else clearSession()
  }
  if (response.status === 401) throw new Error('登录状态已过期，请重新登录后再试。')
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => null) as { code?: unknown; message?: unknown } | null
    const error = new Error(typeof detail?.message === 'string' ? detail.message : 'Assistant stream could not be opened.') as Error & { code?: string }
    if (typeof detail?.code === 'string') error.code = detail.code
    throw error
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  while (true) {
    const { done, value } = await reader.read()
    pending += decoder.decode(value, { stream: !done })
    const frames = pending.split('\n\n')
    pending = done ? '' : frames.pop() ?? ''
    for (const frame of frames) parseSseFrame(frame, onEvent)
    if (done) break
  }
  if (pending.trim()) parseSseFrame(pending, onEvent)
}

async function fetchSse(path: string, init: RequestInit) {
  const token = getAccessToken()
  return fetch(`/api/v1${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      'X-Request-ID': newClientId(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
}

function parseSseFrame(frame: string, onEvent: (event: AiAssistantStreamEvent) => void) {
  const event = frame.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim()
  const data = frame.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim()
  if (!event || !data) return
  const payload = JSON.parse(data) as { run_id?: string; phase?: string; text?: string; message?: AiMessage | string; code?: string }
  if (!payload.run_id) return
  if (event === 'progress' && typeof payload.phase === 'string' && typeof payload.message === 'string') onEvent({ type: 'progress', runId: payload.run_id, phase: payload.phase, message: payload.message })
  if (event === 'delta' && typeof payload.text === 'string') onEvent({ type: 'delta', runId: payload.run_id, text: payload.text })
  if (event === 'completed' && payload.message && typeof payload.message === 'object') onEvent({ type: 'completed', runId: payload.run_id, message: payload.message })
  if (event === 'failed' && typeof payload.message === 'string') onEvent({ type: 'failed', runId: payload.run_id, code: payload.code, message: payload.message })
}
export async function listAiMemories() { const { data } = await api.get<{ items: AiMemory[] }>('/ai/memories'); return data.items }
export async function createAiMemory(memoryType: AiMemory['memory_type'], memoryKey: string, text: string) {
  const { data } = await api.post<AiMemory>('/ai/memories', {
    memory_type: memoryType,
    memory_key: memoryKey,
    memory_value: { text },
    source: 'user',
    confidence: 1,
  })
  return data
}
export async function syncSettingsToAiMemory() { const { data } = await api.post<AiMemory>('/users/me/settings:sync-ai-memory'); return data }
export async function updateAiMemory(memoryId: string, memory_value: Record<string, unknown>, source: string, confidence: number) { const { data } = await api.patch<AiMemory>(`/ai/memories/${memoryId}`, { memory_value, source, confidence }); return data }
export async function deleteAiMemory(memoryId: string) { await api.delete(`/ai/memories/${memoryId}`) }
