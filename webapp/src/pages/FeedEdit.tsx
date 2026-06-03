import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getFeedPost,
  updateFeedPost,
  uploadFeedMedia,
  ApiError,
  ConflictError,
  NotFoundError,
  UnauthorizedError,
  MAX_UPLOAD_BYTES,
} from '../api/client'
import type { FeedPostDetail as FeedPostDetailType } from '../api/types'
import { ErrorScreen } from '../components/ErrorScreen'
import { useTelegram } from '../hooks/useTelegram'
import styles from './FeedCreate.module.css'

type LoadState =
  | 'loading'
  | 'loaded'
  | 'error-not-found'
  | 'error-unauthorized'
  | 'error-network'

type SubmitState =
  | 'idle'
  | 'submitting'
  | 'uploading'
  | 'success'
  | 'error-forbidden'
  | 'error-conflict'
  | 'error-validation'
  | 'error-network'

interface AttachedMedia {
  file_id: string
  media_type: string
  previewUrl: string
}

/**
 * Резолвит существующее медиа поста в формат AttachedMedia для редактора.
 * Бэкенд GET /api/feed/posts/{id} возвращает:
 *   - `photos`: список готовых URL для отображения (карусель/превью).
 *   - `media`: список {file_id, media_type} — оригинальные file_id, которые
 *     надо отправлять обратно в PUT (бэк сравнивает с текущими и решает,
 *     надо ли запускать пере-модерацию).
 *
 * Ограничение MVP: редактор поддерживает только одно медиа за раз. Если
 * у поста было больше одного — берём первое, остальные при сохранении
 * будут удалены (UI пока не поддерживает multi-media-форму).
 */
function buildInitialMedia(post: FeedPostDetailType): AttachedMedia | null {
  const media = post.media ?? []
  if (media.length === 0 || post.photos.length === 0) return null
  const first = media[0]
  const previewUrl = post.photos[0]
  if (!first || !previewUrl) return null
  return {
    file_id: first.file_id,
    media_type: first.media_type,
    previewUrl,
  }
}

export function FeedEdit() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { ready, showBackButton, hideBackButton } = useTelegram()

  const postId = id ? parseInt(id, 10) : NaN

  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [text, setText] = useState('')
  const [attachedMedia, setAttachedMedia] = useState<AttachedMedia | null>(null)
  // Меняли ли мы медиа? Если нет — отправим payload без `media`
  // (бэк трактует undefined как «не трогать»).
  const [mediaDirty, setMediaDirty] = useState(false)
  // Если у фото есть object-URL (загрузили заново), его нужно revoke'нуть.
  const [hasPreviewObjectUrl, setHasPreviewObjectUrl] = useState(false)

  const [submitState, setSubmitState] = useState<SubmitState>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    ready()
    showBackButton(() => navigate(-1))
    return () => hideBackButton()
  }, [ready, showBackButton, hideBackButton, navigate])

  // Префилл поста
  useEffect(() => {
    if (!id || isNaN(postId)) {
      setLoadState('error-not-found')
      return
    }

    void getFeedPost(postId)
      .then((data) => {
        setText(data.text)
        const initial = buildInitialMedia(data)
        if (initial) {
          setAttachedMedia(initial)
        }
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

  // Revoke object-URL у превью при анмаунте, если мы его создавали.
  useEffect(() => {
    return () => {
      if (hasPreviewObjectUrl && attachedMedia) {
        URL.revokeObjectURL(attachedMedia.previewUrl)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''

    if (file.size > MAX_UPLOAD_BYTES) {
      setSubmitState('error-validation')
      setErrorMessage('Фото слишком большое — максимум 5 МБ.')
      return
    }

    setSubmitState('uploading')
    setErrorMessage(null)

    const previewUrl = URL.createObjectURL(file)
    try {
      const result = await uploadFeedMedia(file)
      // Освобождаем предыдущий object-URL, если был наш
      if (hasPreviewObjectUrl && attachedMedia) {
        URL.revokeObjectURL(attachedMedia.previewUrl)
      }
      setAttachedMedia({
        file_id: result.file_id,
        media_type: result.media_type,
        previewUrl,
      })
      setHasPreviewObjectUrl(true)
      setMediaDirty(true)
      setSubmitState('idle')
    } catch (err) {
      URL.revokeObjectURL(previewUrl)
      const msg =
        err instanceof ApiError
          ? err.message
          : 'Не удалось загрузить фото. Попробуйте ещё раз.'
      setSubmitState('error-validation')
      setErrorMessage(msg)
    }
  }

  const handleRemoveMedia = () => {
    if (hasPreviewObjectUrl && attachedMedia) {
      URL.revokeObjectURL(attachedMedia.previewUrl)
    }
    setAttachedMedia(null)
    setHasPreviewObjectUrl(false)
    setMediaDirty(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitState === 'submitting' || submitState === 'uploading') return
    if (!text.trim() && !attachedMedia) return
    if (isNaN(postId)) return

    setSubmitState('submitting')
    setErrorMessage(null)

    const payload: { text: string; media?: { file_id: string; media_type: string }[] } = {
      text: text.trim(),
    }
    if (mediaDirty) {
      payload.media = attachedMedia
        ? [{ file_id: attachedMedia.file_id, media_type: attachedMedia.media_type }]
        : []
    }

    try {
      await updateFeedPost(postId, payload)
      if (hasPreviewObjectUrl && attachedMedia) {
        URL.revokeObjectURL(attachedMedia.previewUrl)
      }
      setSubmitState('success')
      navigate(`/feed/${postId}`)
    } catch (err) {
      if (err instanceof ConflictError) {
        setSubmitState('error-conflict')
        setErrorMessage(
          err.detail ??
            'Пост скрыт модератором или заблокирован — редактирование недоступно.',
        )
      } else if (err instanceof NotFoundError) {
        navigate('/feed')
      } else if (err instanceof UnauthorizedError) {
        setSubmitState('error-forbidden')
        setErrorMessage('Сессия истекла. Откройте Mini App заново.')
      } else if (err instanceof ApiError) {
        if (err.status === 403) {
          // Не автор поста — отправляем в ленту
          navigate('/feed')
          return
        }
        // 422 — модерация либо валидация
        setSubmitState('error-validation')
        setErrorMessage(err.message)
      } else {
        setSubmitState('error-network')
        setErrorMessage('Ошибка сети. Попробуйте ещё раз.')
      }
    }
  }

  if (loadState === 'loading') {
    return (
      <main className={styles.page}>
        <header className={styles.header}>
          <div className={styles.titleBlock}>
            <p className={styles.kicker}>твой вайб - твои люди</p>
            <h1 className={styles.title}>Редактирование</h1>
          </div>
        </header>
      </main>
    )
  }

  if (loadState === 'error-unauthorized') {
    return <ErrorScreen type="unauthorized" />
  }

  if (loadState === 'error-not-found') {
    return <ErrorScreen type="not-found" />
  }

  if (loadState === 'error-network') {
    return <ErrorScreen type="network" onRetry={() => navigate(0)} />
  }

  const isBusy = submitState === 'submitting' || submitState === 'uploading'
  const canSubmit = (text.trim().length > 0 || attachedMedia !== null) && !isBusy

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.backBtn}
          onClick={() => navigate(`/feed/${postId}`)}
          aria-label="Назад к посту"
        >
          ←
        </button>
        <div className={styles.titleBlock}>
          <p className={styles.kicker}>твой вайб - твои люди</p>
          <h1 className={styles.title}>Редактирование</h1>
        </div>
      </header>

      <form className={styles.form} onSubmit={(e) => void handleSubmit(e)} noValidate>
        <label htmlFor="post-text" className={styles.label}>
          Текст поста
        </label>
        <textarea
          id="post-text"
          className={styles.textarea}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            if (
              submitState !== 'idle' &&
              submitState !== 'uploading' &&
              submitState !== 'submitting'
            ) {
              setSubmitState('idle')
              setErrorMessage(null)
            }
          }}
          placeholder="Напишите что-нибудь..."
          rows={6}
          maxLength={4000}
          disabled={isBusy}
          aria-describedby={errorMessage ? 'post-error' : undefined}
        />
        <span className={styles.charCount} aria-live="polite">
          {text.length} / 4000
        </span>

        {attachedMedia && (
          <div className={styles.mediaPreview}>
            <img
              src={attachedMedia.previewUrl}
              alt="Прикреплённое фото"
              className={styles.mediaPreviewImg}
            />
            <button
              type="button"
              className={styles.mediaRemoveBtn}
              onClick={handleRemoveMedia}
              aria-label="Убрать фото"
            >
              ✕
            </button>
          </div>
        )}

        {!attachedMedia && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className={styles.fileInput}
              onChange={(e) => void handleFileChange(e)}
              disabled={isBusy}
              aria-label="Выбрать фото"
            />
            <button
              type="button"
              className={styles.attachBtn}
              onClick={() => fileInputRef.current?.click()}
              disabled={isBusy}
            >
              {submitState === 'uploading' ? 'Загрузка...' : 'Прикрепить фото'}
            </button>
          </>
        )}

        {submitState === 'error-conflict' && (
          <p id="post-error" className={styles.errorForbidden} role="alert">
            {errorMessage ??
              'Пост скрыт модератором или заблокирован — редактирование недоступно.'}
          </p>
        )}

        {submitState === 'error-forbidden' && (
          <p id="post-error" className={styles.errorForbidden} role="alert">
            {errorMessage ?? 'Нет прав на редактирование.'}
          </p>
        )}

        {(submitState === 'error-validation' || submitState === 'error-network') &&
          errorMessage && (
            <p id="post-error" className={styles.errorValidation} role="alert">
              {errorMessage}
            </p>
          )}

        <button
          type="submit"
          className={styles.submitBtn}
          disabled={!canSubmit}
          aria-busy={isBusy}
        >
          {submitState === 'submitting' ? 'Сохранение...' : 'Сохранить'}
        </button>
      </form>
    </main>
  )
}
