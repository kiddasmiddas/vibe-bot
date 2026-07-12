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

export interface FeedMediaItem {
  media_type: string
  file_id: string
}

export interface FeedPostDetail {
  id: number
  author_name: string
  /**
   * User.id автора поста. Заполняется бэком, когда нужно дать UI
   * возможность отличить «свой» пост от чужого (для кнопки «Редактировать»).
   * Может отсутствовать в выдаче — тогда блок управления постом скрыт.
   */
  author_id?: number | null
  text: string
  created_at: string
  /** file_id'ы в порядке position — для отображения в карусели. */
  photos: string[]
  /** Полный набор медиа с media_type — нужен при редактировании поста. */
  media?: FeedMediaItem[]
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
  parent_id: number | null
  replies: FeedComment[]
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
