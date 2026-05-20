// Типы зеркалируют pydantic-схемы бэка (app/api/schemas/creators.py)

// --- Лента постов (feed) ---

export interface FeedPostPreview {
  id: number
  author_name: string
  text: string
  created_at: string
  first_photo_file_id: string | null
}

export interface FeedReactions {
  heart: number
  sparkle: number
  cry: number
  eyes: number
}

export interface FeedPostDetail {
  id: number
  author_name: string
  text: string
  created_at: string
  photos: string[]
  expires_at: string
  reactions: FeedReactions
  my_reaction: string | null
}

export interface FeedComment {
  id: number
  author_name: string
  text: string
  media_type: string | null
  media_file_id: string | null
  created_at: string
}

export interface FeedCommentsResponse {
  items: FeedComment[]
  next_cursor: string | null
}

export interface FeedPostsResponse {
  items: FeedPostPreview[]
  next_cursor: string | null
}

// --- Аллея креаторов ---

export interface PostPreview {
  id: number
  author_display_name: string
  category_id: number
  category_title: string
  first_photo_file_id: string | null
  title: string
  expires_at: string | null
  is_premium_post: boolean
}

export interface PostDetail {
  id: number
  author_display_name: string
  category_id: number
  category_title: string
  photos: string[]
  description: string
  telegram_link: string
  music_file_id: string | null
  expires_at: string | null
  is_premium_post: boolean
}

export interface FeedResponse {
  items: PostPreview[]
  next_cursor: string | null
}
