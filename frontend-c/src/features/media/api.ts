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

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])
const SHA256_H = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
])

function rotr(value: number, shift: number) {
  return (value >>> shift) | (value << (32 - shift))
}

function sha256Sync(input: Uint8Array): string {
  const mlen = input.byteLength
  const paddedLength = Math.ceil((mlen + 9) / 64) * 64
  const padded = new Uint8Array(paddedLength)
  padded.set(input)
  padded[mlen] = 0x80
  let lengthBits = mlen * 8
  for (let index = 0; index < 8; index += 1) {
    padded[paddedLength - 1 - index] = lengthBits & 0xff
    lengthBits = Math.floor(lengthBits / 256)
  }
  const words = new Uint32Array(64)
  const hash = SHA256_H.slice()
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      const base = offset + index * 4
      words[index] = ((padded[base] << 24) | (padded[base + 1] << 16) | (padded[base + 2] << 8) | padded[base + 3]) >>> 0
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotr(words[index - 15], 7) ^ rotr(words[index - 15], 18) ^ (words[index - 15] >>> 3)
      const s1 = rotr(words[index - 2], 17) ^ rotr(words[index - 2], 19) ^ (words[index - 2] >>> 10)
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0
    }
    let a = hash[0], b = hash[1], c = hash[2], d = hash[3]
    let e = hash[4], f = hash[5], g = hash[6], h = hash[7]
    for (let index = 0; index < 64; index += 1) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const temp1 = (h + s1 + ch + SHA256_K[index] + words[index]) >>> 0
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (s0 + maj) >>> 0
      h = g; g = f; f = e; e = (d + temp1) >>> 0; d = c; c = b; b = a; a = (temp1 + temp2) >>> 0
    }
    hash[0] = (hash[0] + a) >>> 0; hash[1] = (hash[1] + b) >>> 0
    hash[2] = (hash[2] + c) >>> 0; hash[3] = (hash[3] + d) >>> 0
    hash[4] = (hash[4] + e) >>> 0; hash[5] = (hash[5] + f) >>> 0
    hash[6] = (hash[6] + g) >>> 0; hash[7] = (hash[7] + h) >>> 0
  }
  let hex = ''
  for (const value of hash) {
    hex += value.toString(16).padStart(8, '0')
  }
  return hex
}

async function sha256(file: File) {
  const data = new Uint8Array(await file.arrayBuffer())
  if (typeof crypto !== 'undefined' && typeof crypto.subtle?.digest === 'function') {
    const bytes = await crypto.subtle.digest('SHA-256', data)
    return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('')
  }
  // Insecure origins (plain HTTP without HTTPS) expose no Web Crypto API; fall
  // back to this bundled pure-JS SHA-256 so uploads keep working on non-secure hosts.
  return sha256Sync(data)
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
