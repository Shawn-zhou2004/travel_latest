import { api } from '@/services/api'

const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const ACCEPTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

interface UploadRequestResponse {
  asset_id: string
  upload_url: string
  headers: Record<string, string>
}

interface UploadCompletionResponse {
  id: string
  status: string
}

interface DownloadUrlResponse {
  url: string
}

export class ImageUploadValidationError extends Error {}

export function validateImageFile(file: File) {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
    throw new ImageUploadValidationError('请选择 JPEG、PNG 或 WebP 图片。')
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new ImageUploadValidationError('图片不能超过 10 MiB。')
  }
}

async function sha256(file: File) {
  const bytes = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function uploadPrivateImage(file: File, purpose: string) {
  validateImageFile(file)
  const { data: request } = await api.post<UploadRequestResponse>('/media/upload-requests', {
    purpose,
    mime_type: file.type,
    size_bytes: file.size,
    sha256: await sha256(file),
  })

  // Presigned URLs receive only the storage headers returned by the API, never session credentials.
  const uploaded = await fetch(request.upload_url, {
    method: 'PUT',
    headers: request.headers,
    body: file,
    credentials: 'omit',
  })
  if (!uploaded.ok) throw new Error('图片没有上传到私有存储，请重试。')

  const etag = uploaded.headers.get('ETag')
  if (!etag) throw new Error('图片上传未返回校验标识，请重试。')

  const { data: completed } = await api.post<UploadCompletionResponse>(`/media/${request.asset_id}:complete`, {
    etag,
    size_bytes: file.size,
  })
  if (completed.status !== 'completed') throw new Error('图片尚未完成处理，请重试。')
  return completed.id
}

export async function getPrivateImageUrl(assetId: string) {
  const { data } = await api.get<DownloadUrlResponse>(`/media/${assetId}/download-url`)
  return data.url
}
