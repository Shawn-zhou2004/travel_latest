import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getPrivateImageUrl, ImageUploadValidationError, uploadPrivateImage, validateImageFile } from './api'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('private image upload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer) } })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('rejects unsupported files and files larger than 10 MiB before requesting an upload URL', () => {
    expect(() => validateImageFile(new File(['image'], 'photo.gif', { type: 'image/gif' }))).toThrow(ImageUploadValidationError)
    expect(() => validateImageFile(new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'photo.png', { type: 'image/png' }))).toThrow('10 MiB')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('uses the request, credential-free PUT, and completion workflow', async () => {
    const file = new File(['image'], 'reference.webp', { type: 'image/webp' })
    Object.assign(file, { arrayBuffer: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3]).buffer) })
    api.post
      .mockResolvedValueOnce({ data: { asset_id: 'asset-1', upload_url: 'https://storage.example/upload', headers: { 'Content-Type': 'image/webp', 'x-amz-meta-sha256': '0'.repeat(64) } } })
      .mockResolvedValueOnce({ data: { id: 'asset-1', status: 'completed' } })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, headers: new Headers({ ETag: '"etag-1"' }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(uploadPrivateImage(file, 'itinerary_reference')).resolves.toBe('asset-1')

    expect(api.post).toHaveBeenNthCalledWith(1, '/media/upload-requests', expect.objectContaining({ purpose: 'itinerary_reference', mime_type: 'image/webp', size_bytes: file.size, sha256: '0'.repeat(64) }))
    expect(fetchMock).toHaveBeenCalledWith('https://storage.example/upload', expect.objectContaining({ method: 'PUT', headers: { 'Content-Type': 'image/webp', 'x-amz-meta-sha256': '0'.repeat(64) }, body: file, credentials: 'omit' }))
    expect(api.post).toHaveBeenNthCalledWith(2, '/media/asset-1:complete', { etag: '"etag-1"', size_bytes: file.size })
  })

  it('requests a private URL only for the requested asset', async () => {
    api.get.mockResolvedValue({ data: { url: 'https://storage.example/private-avatar' } })

    await expect(getPrivateImageUrl('asset-1')).resolves.toBe('https://storage.example/private-avatar')

    expect(api.get).toHaveBeenCalledWith('/media/asset-1/download-url')
  })
})
