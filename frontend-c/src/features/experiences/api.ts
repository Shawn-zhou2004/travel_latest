import { api } from '@/services/api'

export interface ExperienceProvider {
  id: string
  name: string
}

export interface ExperienceSession {
  id: string
  starts_at: string
  remaining_capacity: number
  status: 'scheduled' | 'cancelled' | 'completed'
}

export interface ExperienceSummary {
  id: string
  title: string
  price_amount: number | string
  currency: string
  provider: ExperienceProvider
  status: 'published'
}

export interface ExperienceDetail extends ExperienceSummary {
  description: string
  meeting_point?: string
  cancellation_policy: string
  sessions: ExperienceSession[]
}

interface ExperiencePage {
  items: ExperienceSummary[]
  next_cursor?: string
}

export async function listExperiences(params?: { city_code?: string; provider_id?: string }) {
  const { data } = await api.get<ExperiencePage>('/experiences', { params })
  return data
}

export async function getExperience(experienceId: string) {
  const { data } = await api.get<ExperienceDetail>(`/experiences/${experienceId}`)
  return data
}
