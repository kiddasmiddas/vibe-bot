import type {
  FeedResponse,
  PostDetail,
  FeedPostsResponse,
  FeedPostDetail,
  FeedCommentsResponse,
  FeedReactions,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class UnauthorizedError extends Error {
  constructor() {
    super('Unauthorized')
    this.name = 'UnauthorizedError'
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NetworkError'
  }
}

export class NotFoundError extends Error {
  constructor() {
    super('Not Found')
    this.name = 'NotFoundError'
  }
}

export class ApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

function getInitData(): string | null {
  try {
    const tg = window.Telegram?.WebApp
    const data = tg?.initData
    return data && data.length > 0 ? data : null
  } catch {
    return null
  }
}

interface FetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  body?: unknown
}

async function fetchJson<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { method = 'GET', body } = options
  const initData = getInitData()
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (initData) {
    headers['X-Telegram-Init-Data'] = initData
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    throw new NetworkError(err instanceof Error ? err.message : 'Network request failed')
  }

  if (response.status === 401) {
    throw new UnauthorizedError()
  }
  if (response.status === 404) {
    throw new NotFoundError()
  }

  if (response.status === 403 || response.status === 422) {
    let detail = `HTTP ${response.status}`
    try {
      const json = (await response.json()) as { detail?: string }
      if (json.detail) detail = json.detail
    } catch {
      // ignore parse errors
    }
    throw new ApiError(detail)
  }

  if (response.status === 204) {
    return undefined as unknown as T
  }

  if (!response.ok) {
    throw new NetworkError(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

export async function getFeed(cursor?: string): Promise<FeedResponse> {
  const params = new URLSearchParams({ limit: '20' })
  if (cursor) {
    params.set('cursor', cursor)
  }
  return fetchJson<FeedResponse>(`/api/creators/feed?${params.toString()}`)
}

export async function getPost(id: number): Promise<PostDetail> {
  return fetchJson<PostDetail>(`/api/creators/${id}`)
}

export async function getFeedPosts(cursor?: string): Promise<FeedPostsResponse> {
  const params = new URLSearchParams({ limit: '20' })
  if (cursor) {
    params.set('cursor', cursor)
  }
  return fetchJson<FeedPostsResponse>(`/api/feed/posts?${params.toString()}`)
}

export async function getFeedPost(id: number): Promise<FeedPostDetail> {
  return fetchJson<FeedPostDetail>(`/api/feed/posts/${id}`)
}

export interface MediaItem {
  media_type: string
  file_id: string
}

export interface CreatePostResult {
  id: number
  pending_review: boolean
}

export async function createFeedPost(
  text: string,
  media: MediaItem[],
): Promise<CreatePostResult> {
  return fetchJson<CreatePostResult>('/api/feed/posts', {
    method: 'POST',
    body: { text, media },
  })
}

export async function getFeedComments(
  postId: number,
  cursor?: string,
): Promise<FeedCommentsResponse> {
  const params = new URLSearchParams({ limit: '20' })
  if (cursor) params.set('cursor', cursor)
  return fetchJson<FeedCommentsResponse>(`/api/feed/posts/${postId}/comments?${params.toString()}`)
}

export interface CreateCommentBody {
  text?: string
  media_type?: string
  media_file_id?: string
}

export async function createFeedComment(
  postId: number,
  body: CreateCommentBody,
): Promise<{ id: number }> {
  return fetchJson<{ id: number }>(`/api/feed/posts/${postId}/comments`, {
    method: 'POST',
    body,
  })
}

export interface ReactionResponse {
  counts: FeedReactions
  my_reaction: string | null
}

export async function setFeedReaction(
  postId: number,
  reactionType: string,
): Promise<ReactionResponse> {
  return fetchJson<ReactionResponse>(`/api/feed/posts/${postId}/reaction`, {
    method: 'PUT',
    body: { reaction_type: reactionType },
  })
}

export async function removeFeedReaction(postId: number): Promise<ReactionResponse> {
  return fetchJson<ReactionResponse>(`/api/feed/posts/${postId}/reaction`, {
    method: 'DELETE',
  })
}

export async function deleteFeedComment(commentId: number): Promise<void> {
  return fetchJson<void>(`/api/feed/comments/${commentId}`, {
    method: 'DELETE',
  })
}

export interface UploadMediaResult {
  file_id: string
  media_type: string
}

/** Максимальный вес загружаемого фото — 5 МБ. Совпадает с лимитом бэкенда
 *  (`app/api/routes/feed.py:_MAX_UPLOAD_BYTES`). */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

export async function uploadFeedMedia(file: File): Promise<UploadMediaResult> {
  const initData = getInitData()
  const headers: HeadersInit = {}
  if (initData) {
    headers['X-Telegram-Init-Data'] = initData
  }
  // Do NOT set Content-Type — browser sets it with the correct multipart boundary.
  const formData = new FormData()
  formData.append('file', file)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/feed/upload`, {
      method: 'POST',
      headers,
      body: formData,
    })
  } catch (err) {
    throw new NetworkError(err instanceof Error ? err.message : 'Network request failed')
  }

  if (response.status === 401) throw new UnauthorizedError()
  if (response.status === 404) throw new NotFoundError()

  if (response.status === 422 || response.status === 502 || response.status === 503) {
    let detail = `HTTP ${response.status}`
    try {
      const json = (await response.json()) as { detail?: string }
      if (json.detail) detail = json.detail
    } catch {
      // ignore parse errors
    }
    throw new ApiError(detail)
  }

  if (!response.ok) {
    throw new NetworkError(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json() as Promise<UploadMediaResult>
}
