import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { FeedPostPreview } from '../api/types'
import styles from './FeedPostCard.module.css'

const MAX_TEXT_LENGTH = 120

interface FeedPostCardProps {
  post: FeedPostPreview
}

export function FeedPostCard({ post }: FeedPostCardProps) {
  const navigate = useNavigate()
  const [photoError, setPhotoError] = useState(false)

  const handleClick = () => {
    navigate(`/feed/${post.id}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      navigate(`/feed/${post.id}`)
    }
  }

  const showPhoto = post.first_photo_file_id !== null && !photoError
  const truncatedText =
    post.text.length > MAX_TEXT_LENGTH ? post.text.slice(0, MAX_TEXT_LENGTH) + '…' : post.text

  return (
    <article
      className={styles.card}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Пост от ${post.author_name}`}
    >
      <div className={styles.photoWrapper}>
        {showPhoto ? (
          <img
            className={styles.photo}
            src={post.first_photo_file_id ?? ''}
            alt={`Фото поста от ${post.author_name}`}
            loading="lazy"
            onError={() => setPhotoError(true)}
          />
        ) : (
          <div className={styles.photoFallback} aria-hidden="true">
            <span className={styles.photoFallbackIcon}>📝</span>
            <span className={styles.photoFallbackLabel}>Пост</span>
          </div>
        )}
      </div>

      <div className={styles.body}>
        <p className={styles.author}>{post.author_name}</p>
        <p className={styles.text}>{truncatedText}</p>
      </div>
    </article>
  )
}
