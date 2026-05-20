import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getFeedPost,
  getFeedComments,
  createFeedComment,
  uploadFeedMedia,
  UnauthorizedError,
  NotFoundError,
  ApiError,
  MAX_UPLOAD_BYTES,
} from '../api/client'
import type { FeedPostDetail as FeedPostDetailType, FeedComment } from '../api/types'
import { ErrorScreen } from '../components/ErrorScreen'
import { FeedReactions } from '../components/FeedReactions'
import { useTelegram } from '../hooks/useTelegram'
import styles from './FeedPostDetail.module.css'

type LoadState = 'loading' | 'loaded' | 'error-not-found' | 'error-unauthorized' | 'error-network'
type CommentLoadState = 'idle' | 'loading' | 'loading-more' | 'done' | 'error'
type CommentSubmitState =
  | 'idle'
  | 'uploading'
  | 'submitting'
  | 'error-forbidden'
  | 'error-validation'
  | 'error-network'

interface AttachedCommentMedia {
  file_id: string
  media_type: string
  previewUrl: string
}

interface PhotoSlideProps {
  fileId: string
  alt: string
}

function PhotoSlide({ fileId, alt }: PhotoSlideProps) {
  const [hasError, setHasError] = useState(false)

  return (
    <div className={styles.carouselSlide} role="listitem">
      {hasError ? (
        <div className={styles.carouselFallback} aria-label="Нет изображения">
          <span className={styles.carouselFallbackIcon} aria-hidden="true">📝</span>
          <span className={styles.carouselFallbackLabel}>Пост</span>
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

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatCommentDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

export function FeedPostDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { showBackButton, hideBackButton } = useTelegram()

  const [post, setPost] = useState<FeedPostDetailType | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [activeSlide, setActiveSlide] = useState(0)
  const trackRef = useRef<HTMLDivElement | null>(null)

  // Comments state
  const [comments, setComments] = useState<FeedComment[]>([])
  const [commentLoadState, setCommentLoadState] = useState<CommentLoadState>('idle')
  const [commentCursor, setCommentCursor] = useState<string | null>(null)
  const hasMoreCommentsRef = useRef(true)

  // Comment form state
  const [commentText, setCommentText] = useState('')
  const [commentSubmitState, setCommentSubmitState] = useState<CommentSubmitState>('idle')
  const [commentSubmitError, setCommentSubmitError] = useState<string | null>(null)
  const [attachedMedia, setAttachedMedia] = useState<AttachedCommentMedia | null>(null)
  const commentFileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    showBackButton(() => navigate(-1))
    return () => hideBackButton()
  }, [showBackButton, hideBackButton, navigate])

  const postId = id ? parseInt(id, 10) : NaN

  useEffect(() => {
    if (!id || isNaN(postId)) {
      setLoadState('error-not-found')
      return
    }

    void getFeedPost(postId)
      .then((data) => {
        setPost(data)
        setLoadState('loaded')
      })
      .catch((err) => {
        if (err instanceof UnauthorizedError) {
          setLoadState('error-unauthorized')
        } else if (err instanceof NotFoundError) {
          setLoadState('error-not-found')
        } else {
          setLoadState('error-network')
        }
      })
  }, [id, postId])

  const loadComments = useCallback(
    async (cursor?: string) => {
      if (isNaN(postId) || !hasMoreCommentsRef.current) return
      const isFirst = cursor === undefined

      setCommentLoadState(isFirst ? 'loading' : 'loading-more')
      try {
        const data = await getFeedComments(postId, cursor ?? undefined)
        setComments((prev) => (isFirst ? data.items : [...prev, ...data.items]))
        if (data.next_cursor) {
          setCommentCursor(data.next_cursor)
        } else {
          hasMoreCommentsRef.current = false
          setCommentCursor(null)
        }
        setCommentLoadState('done')
      } catch {
        setCommentLoadState('error')
      }
    },
    [postId],
  )

  // Load first page of comments when post is loaded
  useEffect(() => {
    if (loadState === 'loaded') {
      void loadComments(undefined)
    }
  }, [loadState, loadComments])

  const handleCarouselScroll = () => {
    const track = trackRef.current
    if (!track || !post) return
    const slideWidth = track.offsetWidth
    const scrollLeft = track.scrollLeft
    const index = Math.round(scrollLeft / slideWidth)
    setActiveSlide(Math.min(index, post.photos.length - 1))
  }

  // Comment photo attachment
  const handleCommentFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''

    if (file.size > MAX_UPLOAD_BYTES) {
      setCommentSubmitState('error-validation')
      setCommentSubmitError('Фото слишком большое — максимум 5 МБ.')
      return
    }

    setCommentSubmitState('uploading')
    setCommentSubmitError(null)

    const previewUrl = URL.createObjectURL(file)
    try {
      const result = await uploadFeedMedia(file)
      setAttachedMedia({ file_id: result.file_id, media_type: result.media_type, previewUrl })
      setCommentSubmitState('idle')
    } catch (err) {
      URL.revokeObjectURL(previewUrl)
      const msg =
        err instanceof ApiError
          ? err.message
          : 'Не удалось загрузить фото. Попробуйте ещё раз.'
      setCommentSubmitState('error-validation')
      setCommentSubmitError(msg)
    }
  }

  const handleRemoveCommentMedia = () => {
    if (attachedMedia) URL.revokeObjectURL(attachedMedia.previewUrl)
    setAttachedMedia(null)
  }

  const handleCommentSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const isBusy =
      commentSubmitState === 'submitting' || commentSubmitState === 'uploading'
    if (isBusy) return

    const hasText = commentText.trim().length > 0
    const hasMedia = attachedMedia !== null

    // XOR: must have exactly one of text or media
    if (!hasText && !hasMedia) return

    setCommentSubmitState('submitting')
    setCommentSubmitError(null)

    try {
      const body = hasMedia
        ? { media_type: attachedMedia.media_type, media_file_id: attachedMedia.file_id }
        : { text: commentText.trim() }

      await createFeedComment(postId, body)

      setCommentText('')
      if (attachedMedia) {
        URL.revokeObjectURL(attachedMedia.previewUrl)
        setAttachedMedia(null)
      }
      setCommentSubmitState('idle')
      // Reload comments from beginning to show new comment
      hasMoreCommentsRef.current = true
      setComments([])
      setCommentCursor(null)
      await loadComments(undefined)
    } catch (err) {
      if (err instanceof ApiError) {
        const msg = err.message
        const isForbidden =
          msg.toLowerCase().includes('анкет') ||
          msg.toLowerCase().includes('ограни') ||
          msg.toLowerCase().includes('forbidden') ||
          msg.toLowerCase().includes('premium') ||
          msg.toLowerCase().includes('запрещ')
        setCommentSubmitState(isForbidden ? 'error-forbidden' : 'error-validation')
        setCommentSubmitError(isForbidden ? 'Медиа в комментариях — только для Premium.' : msg)
      } else {
        setCommentSubmitState('error-network')
        setCommentSubmitError('Ошибка сети.')
      }
    }
  }

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

  const hasMultiplePhotos = post.photos.length > 1
  const commentIsBusy =
    commentSubmitState === 'submitting' || commentSubmitState === 'uploading'
  const canSubmitComment =
    (commentText.trim().length > 0 || attachedMedia !== null) && !commentIsBusy

  return (
    <main className={styles.page}>
      <button
        className={styles.backButton}
        onClick={() => navigate(-1)}
        aria-label="Назад в Ленту"
      >
        ← Назад
      </button>

      {/* Карусель фотографий */}
      <div className={styles.carousel} aria-label="Фотографии поста">
        <div
          ref={trackRef}
          className={styles.carouselTrack}
          onScroll={handleCarouselScroll}
          role="list"
          aria-label={`${post.photos.length} фото`}
        >
          {post.photos.length > 0 ? (
            post.photos.map((fileId, idx) => (
              <PhotoSlide
                key={idx}
                fileId={fileId}
                alt={`Фото ${idx + 1} — ${post.author_name}`}
              />
            ))
          ) : (
            <div className={styles.carouselSlide} role="listitem">
              <div className={styles.carouselFallback}>
                <span className={styles.carouselFallbackIcon} aria-hidden="true">📝</span>
                <span className={styles.carouselFallbackLabel}>Пост</span>
              </div>
            </div>
          )}
        </div>

        {hasMultiplePhotos && (
          <div className={styles.carouselDots} aria-label={`Слайд ${activeSlide + 1} из ${post.photos.length}`}>
            {post.photos.map((_, idx) => (
              <div
                key={idx}
                className={`${styles.dot} ${idx === activeSlide ? styles.dotActive : ''}`}
                aria-hidden="true"
              />
            ))}
          </div>
        )}
      </div>

      {/* Контент */}
      <div className={styles.content}>
        <p className={styles.author}>{post.author_name}</p>
        <p className={styles.date}>{formatDate(post.created_at)}</p>
        <p className={styles.text}>{post.text}</p>
      </div>

      {/* Реакции */}
      <FeedReactions
        postId={post.id}
        reactions={post.reactions}
        myReaction={post.my_reaction}
      />

      {/* Комментарии */}
      <section className={styles.commentsSection} aria-label="Комментарии">
        <h2 className={styles.commentsTitle}>Комментарии</h2>

        {commentLoadState === 'loading' && (
          <div className={styles.commentsLoading} aria-label="Загрузка комментариев">
            <div className={styles.spinnerSmall} aria-hidden="true" />
          </div>
        )}

        {commentLoadState !== 'loading' && comments.length === 0 && commentLoadState === 'done' && (
          <p className={styles.noComments}>Комментариев пока нет. Будьте первым!</p>
        )}

        {commentLoadState === 'error' && (
          <div className={styles.commentsErrorBlock}>
            <p className={styles.commentsError}>Не удалось загрузить комментарии.</p>
            <button
              type="button"
              className={styles.commentsRetryBtn}
              onClick={() => {
                hasMoreCommentsRef.current = true
                void loadComments(undefined)
              }}
            >
              Повторить
            </button>
          </div>
        )}

        {comments.length > 0 && (
          <ul className={styles.commentsList} aria-label="Список комментариев">
            {comments.map((comment) => (
              <li key={comment.id} className={styles.commentItem}>
                <div className={styles.commentHeader}>
                  <span className={styles.commentAuthor}>{comment.author_name}</span>
                  <span className={styles.commentDate}>{formatCommentDate(comment.created_at)}</span>
                </div>
                {comment.text && <p className={styles.commentText}>{comment.text}</p>}
                {comment.media_file_id && (
                  <img
                    src={comment.media_file_id}
                    alt="Медиа в комментарии"
                    className={styles.commentMediaImg}
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = 'none'
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        {hasMoreCommentsRef.current && commentLoadState === 'done' && commentCursor && (
          <button
            type="button"
            className={styles.loadMoreBtn}
            onClick={() => void loadComments(commentCursor)}
          >
            Показать ещё
          </button>
        )}

        {commentLoadState === 'loading-more' && (
          <div className={styles.commentsLoading} aria-label="Загрузка комментариев">
            <div className={styles.spinnerSmall} aria-hidden="true" />
          </div>
        )}

        {/* Форма комментария */}
        <form
          className={styles.commentForm}
          onSubmit={(e) => void handleCommentSubmit(e)}
          noValidate
          aria-label="Форма комментария"
        >
          {commentSubmitState === 'error-forbidden' && (
            <p className={styles.commentError} role="alert" id="comment-error">
              {commentSubmitError ?? 'Нужна анкета / вы ограничены в отправке комментариев.'}
            </p>
          )}
          {(commentSubmitState === 'error-validation' || commentSubmitState === 'error-network') &&
            commentSubmitError && (
              <p className={styles.commentError} role="alert" id="comment-error">
                {commentSubmitError}
              </p>
            )}

          {/* Превью прикреплённого фото */}
          {attachedMedia && (
            <div className={styles.commentMediaPreview}>
              <img
                src={attachedMedia.previewUrl}
                alt="Прикреплённое фото"
                className={styles.commentMediaPreviewImg}
              />
              <button
                type="button"
                className={styles.commentMediaRemoveBtn}
                onClick={handleRemoveCommentMedia}
                aria-label="Убрать фото"
              >
                ✕
              </button>
            </div>
          )}

          <div className={styles.commentInputRow}>
            {/* Скрытый file input */}
            <input
              ref={commentFileInputRef}
              type="file"
              accept="image/*"
              className={styles.fileInputHidden}
              onChange={(e) => void handleCommentFileChange(e)}
              disabled={commentIsBusy}
              aria-label="Прикрепить фото к комментарию"
            />

            {/* Кнопка-иконка камеры */}
            <button
              type="button"
              className={styles.commentAttachBtn}
              onClick={() => commentFileInputRef.current?.click()}
              disabled={commentIsBusy || attachedMedia !== null}
              aria-label="Прикрепить фото"
              title="Прикрепить фото (только Premium)"
            >
              {commentSubmitState === 'uploading' ? '…' : '📷'}
            </button>

            <textarea
              id="comment-text"
              className={styles.commentInput}
              value={commentText}
              onChange={(e) => {
                setCommentText(e.target.value)
                if (
                  commentSubmitState !== 'idle' &&
                  commentSubmitState !== 'uploading'
                ) {
                  setCommentSubmitState('idle')
                  setCommentSubmitError(null)
                }
              }}
              placeholder={attachedMedia ? 'Фото приложено' : 'Написать комментарий...'}
              rows={2}
              maxLength={1000}
              disabled={commentIsBusy || attachedMedia !== null}
              aria-label="Текст комментария"
              aria-describedby={commentSubmitError ? 'comment-error' : undefined}
            />
            <button
              type="submit"
              className={styles.commentSubmitBtn}
              disabled={!canSubmitComment}
              aria-busy={commentIsBusy}
              aria-label="Отправить комментарий"
            >
              {commentSubmitState === 'submitting' ? '…' : 'Отправить'}
            </button>
          </div>
        </form>
      </section>
    </main>
  )
}
