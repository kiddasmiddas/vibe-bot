import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getPost, UnauthorizedError, NetworkError, NotFoundError } from '../api/client'
import type { PostDetail } from '../api/types'
import { ErrorScreen } from '../components/ErrorScreen'
import { useTelegram } from '../hooks/useTelegram'
import styles from './PostDetail.module.css'

type LoadState = 'loading' | 'loaded' | 'error-not-found' | 'error-unauthorized' | 'error-network'

interface PhotoSlideProps {
  fileId: string
  alt: string
  categoryTitle: string
}

function PhotoSlide({ fileId, alt, categoryTitle }: PhotoSlideProps) {
  const [hasError, setHasError] = useState(false)

  return (
    <div className={styles.carouselSlide} role="listitem">
      {hasError ? (
        <div className={styles.carouselFallback} aria-label="Нет изображения">
          <span className={styles.carouselFallbackIcon} aria-hidden="true">🎨</span>
          <span className={styles.carouselFallbackLabel}>{categoryTitle}</span>
        </div>
      ) : (
        <img
          className={styles.carouselImage}
          src={fileId}
          alt={alt}
          onError={() => setHasError(true)}
        />
      )}
    </div>
  )
}

export function PostDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { showBackButton, hideBackButton, openTelegramLink } = useTelegram()

  const [post, setPost] = useState<PostDetail | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')

  useEffect(() => {
    showBackButton(() => navigate(-1))
    return () => hideBackButton()
  }, [showBackButton, hideBackButton, navigate])

  useEffect(() => {
    if (!id) {
      setLoadState('error-not-found')
      return
    }

    const postId = parseInt(id, 10)
    if (isNaN(postId)) {
      setLoadState('error-not-found')
      return
    }

    void getPost(postId)
      .then((data) => {
        setPost(data)
        setLoadState('loaded')
      })
      .catch((err) => {
        if (err instanceof UnauthorizedError) {
          setLoadState('error-unauthorized')
        } else if (err instanceof NotFoundError) {
          setLoadState('error-not-found')
        } else if (err instanceof NetworkError) {
          setLoadState('error-network')
        } else {
          setLoadState('error-network')
        }
      })
  }, [id])

  if (loadState === 'loading') {
    return (
      <main className={styles.page}>
        <div className={styles.loadingWrapper} aria-label="Загрузка поста">
          <div className={styles.spinner} aria-hidden="true" />
        </div>
      </main>
    )
  }

  if (loadState === 'error-not-found') {
    return <ErrorScreen type="not-found" />
  }

  if (loadState === 'error-unauthorized') {
    return <ErrorScreen type="unauthorized" />
  }

  if (loadState === 'error-network' || post === null) {
    return <ErrorScreen type="network" onRetry={() => navigate(0)} />
  }

  return (
    <main className={styles.page}>
      <button
        className={styles.backButton}
        onClick={() => navigate(-1)}
        aria-label="Назад в Аллею креаторов"
      >
        ← Назад
      </button>

      {/* Карусель фотографий */}
      <div className={styles.carousel} aria-label="Фотографии поста">
        <div
          className={styles.carouselTrack}
          role="list"
          aria-label={`${post.photos.length} фото`}
        >
          {post.photos.length > 0 ? (
            post.photos.map((fileId, idx) => (
              <PhotoSlide
                key={idx}
                fileId={fileId}
                alt={`Фото ${idx + 1} — ${post.author_display_name}`}
                categoryTitle={post.category_title}
              />
            ))
          ) : (
            <div className={styles.carouselSlide} role="listitem">
              <div className={styles.carouselFallback}>
                <span className={styles.carouselFallbackIcon} aria-hidden="true">🎨</span>
                <span className={styles.carouselFallbackLabel}>{post.category_title}</span>
              </div>
            </div>
          )}
        </div>

      </div>

      {/* Контент */}
      <div className={styles.content}>
        <div className={styles.metaRow}>
          {post.category_title && (
            <span className={styles.categoryBadge}>{post.category_title}</span>
          )}
        </div>

        <p className={styles.author}>{post.author_display_name}</p>

        <p className={styles.description}>{post.description}</p>

        <button
          className={styles.channelButton}
          onClick={() => openTelegramLink(post.telegram_link)}
          aria-label={`Перейти в канал автора ${post.author_display_name}`}
        >
          Перейти в канал автора
        </button>
      </div>
    </main>
  )
}
