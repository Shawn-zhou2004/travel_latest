import { api } from '@/services/api'

export type ExperienceStatus = 'draft' | 'published' | 'archived'
export type ExperienceSessionStatus = 'scheduled' | 'cancelled' | 'completed'

export interface ProviderExperienceSession {
  id: string
  starts_at: string
  capacity: number
  reserved_count: number
  price_amount: string | null
  currency: string | null
  status: ExperienceSessionStatus
}

export interface ProviderExperience {
  id: string
  provider_id: string
  title: string
  description: string
  poi_id: string
  poi_name: string
  poi_address: string
  price_amount: string
  currency: string
  cancellation_policy: string
  status: ExperienceStatus
  sessions: ProviderExperienceSession[]
  created_at: string
  updated_at: string
}

export interface ExperienceInput {
  title: string
  description: string
  poi_id: string
  price_amount: string
  currency: string
  cancellation_policy: string
  status: Exclude<ExperienceStatus, 'archived'>
}

export interface SessionInput {
  starts_at: string
  capacity: number
  price_amount: string | null
  currency: string | null
}

export interface ProviderBooking {
  id: string
  experience_title: string
  starts_at: string
  traveler_count: number
  status: 'reserved' | 'verified' | 'cancelled'
  verified_at: string | null
}

interface ExperiencePage { items: ProviderExperience[] }

export async function listProviderExperiences(providerId: string) {
  const { data } = await api.get<ExperiencePage>('/provider/experiences', { params: { provider_id: providerId } })
  return data.items
}

export async function createProviderExperience(providerId: string, body: ExperienceInput) {
  const { data } = await api.post<ProviderExperience>('/provider/experiences', body, { params: { provider_id: providerId } })
  return data
}

export async function updateProviderExperience(providerId: string, experienceId: string, body: ExperienceInput) {
  const { data } = await api.put<ProviderExperience>(`/provider/experiences/${experienceId}`, body, { params: { provider_id: providerId } })
  return data
}

export async function createProviderExperienceSession(providerId: string, experienceId: string, body: SessionInput) {
  const { data } = await api.post<ProviderExperienceSession>(`/provider/experiences/${experienceId}/sessions`, body, { params: { provider_id: providerId } })
  return data
}

export async function listProviderBookings(providerId: string, status = 'reserved') {
  const { data } = await api.get<{ items: ProviderBooking[] }>('/provider/experience-bookings', {
    params: { provider_id: providerId, status },
  })
  return data.items
}

export async function verifyProviderBooking(providerId: string, bookingId: string, verificationCode: string) {
  const { data } = await api.post<{ id: string; status: 'verified'; verified_at: string }>(
    `/provider/experience-bookings/${bookingId}:verify`,
    { verification_code: verificationCode },
    { params: { provider_id: providerId } },
  )
  return data
}
