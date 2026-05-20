import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { PostPreview } from '../api/types'
import styles from './PostCard.module.css'

interface PostCardProps {
  post: PostPreview
}

export function PostCard({ post }: PostCardProps) {
  const navigate = useNavigate()
  const [photoError, setPhotoError] = useState(false)

  const handleClick = () => {
    navigate(`/post/${post.id}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      navigate(`/post/${post.id}`)
    }
  }

  const showPhoto = post.first_photo_file_id !== null && !photoError

  return (
    <article
      className={styles.card}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Пост: ${post.title}`}
    >
      <div className={styles.photoWrapper}>
        {showPhoto ? (
          <img
            className={styles.photo}
            src={post.first_photo_file_id ?? ''}
            alt={post.title}
            loading="lazy"
            onError={() => setPhotoError(true)}
          />
        ) : (
          <div className={styles.photoFallback} aria-hidden="true">
            <span className={styles.photoFallbackIcon}>🎨</span>
            <span className={styles.photoFallbackLabel}>{post.category_title}</span>
          </div>
        )}
      </div>

      <div className={styles.body}>
        {post.category_title && (
          <span className={styles.categoryBadge}>{post.category_title}</span>
        )}
        <h3 className={styles.title}>{post.title}</h3>
        <p className={styles.author}>{post.author_display_name}</p>
      </div>
    </article>
  )
}
