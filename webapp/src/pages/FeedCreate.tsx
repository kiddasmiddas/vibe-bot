import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createFeedPost, uploadFeedMedia, ApiError, MAX_UPLOAD_BYTES } from '../api/client'
import { useTelegram } from '../hooks/useTelegram'
import styles from './FeedCreate.module.css'

type SubmitState =
  | 'idle'
  | 'submitting'
  | 'uploading'
  | 'success-pending'
  | 'error-forbidden'
  | 'error-validation'
  | 'error-network'

interface AttachedMedia {
  file_id: string
  media_type: string
  previewUrl: string
}

export function FeedCreate() {
  const navigate = useNavigate()
  const { ready, showBackButton, hideBackButton } = useTelegram()

  useEffect(() => {
    ready()
    showBackButton(() => navigate(-1))
    return () => hideBackButton()
  }, [ready, showBackButton, hideBackButton, navigate])

  const [text, setText] = useState('')
  const [submitState, setSubmitState] = useState<SubmitState>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [attachedMedia, setAttachedMedia] = useState<AttachedMedia | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Reset file input so the same file can be re-selected after removal
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
      setAttachedMedia({ file_id: result.file_id, media_type: result.media_type, previewUrl })
      setSubmitState('idle')
    } catch (err) {
      URL.revokeObjectURL(previewUrl)
      let msg = 'Не удалось загрузить фото. Попробуйте ещё раз.'
      if (err instanceof ApiError) {
        msg = err.status === 429 ? 'Слишком часто. Подожди немного и попробуй снова.' : err.message
      }
      setSubmitState('error-validation')
      setErrorMessage(msg)
    }
  }

  const handleRemoveMedia = () => {
    if (attachedMedia) {
      URL.revokeObjectURL(attachedMedia.previewUrl)
    }
    setAttachedMedia(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitState === 'submitting' || submitState === 'uploading') return
    if (!text.trim() && !attachedMedia) return

    setSubmitState('submitting')
    setErrorMessage(null)

    const media = attachedMedia
      ? [{ media_type: attachedMedia.media_type, file_id: attachedMedia.file_id }]
      : []

    try {
      const result = await createFeedPost(text.trim(), media)
      if (attachedMedia) URL.revokeObjectURL(attachedMedia.previewUrl)
      if (result.pending_review) {
        // Пост ушёл на премодерацию — в ленте его пока не будет.
        setSubmitState('success-pending')
        return
      }
      navigate('/feed')
    } catch (err) {
      if (err instanceof ApiError) {
        // 403 — нет завершённой анкеты; 429 — троттлинг; остальное (422
        // лимит/валидация) показываем с текстом ответа сервера.
        setSubmitState(err.status === 403 ? 'error-forbidden' : 'error-validation')
        setErrorMessage(
          err.status === 429 ? 'Слишком часто. Подожди немного и попробуй снова.' : err.message,
        )
      } else {
        setSubmitState('error-network')
        setErrorMessage('Ошибка сети. Попробуйте ещё раз.')
      }
    }
  }

  const isBusy = submitState === 'submitting' || submitState === 'uploading'
  const canSubmit = (text.trim().length > 0 || attachedMedia !== null) && !isBusy

  if (submitState === 'success-pending') {
    return (
      <main className={styles.page}>
        <div className={styles.pendingScreen}>
          <span className={styles.pendingIcon} aria-hidden="true">🕓</span>
          <h2 className={styles.pendingTitle}>Пост отправлен на проверку</h2>
          <p className={styles.pendingText}>
            Первые посты нового автора проверяет модератор. Пост появится
            в Ленте после одобрения.
          </p>
          <button
            type="button"
            className={styles.pendingBtn}
            onClick={() => navigate('/feed')}
          >
            В Ленту
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.backBtn}
          onClick={() => navigate('/feed')}
          aria-label="Назад в ленту"
        >
          ←
        </button>
        <div className={styles.titleBlock}>
          <p className={styles.kicker}>твой вайб - твои люди</p>
          <h1 className={styles.title}>Новый пост</h1>
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
            if (submitState !== 'idle' && submitState !== 'uploading') {
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

        {/* Прикреплённое фото */}
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

        {/* Кнопка прикрепить фото */}
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

        {submitState === 'error-forbidden' && (
          <p id="post-error" className={styles.errorForbidden} role="alert">
            Сначала заполни анкету, чтобы публиковать посты.
          </p>
        )}

        {(submitState === 'error-validation' || submitState === 'error-network') && errorMessage && (
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
          {submitState === 'submitting' ? 'Публикация...' : 'Опубликовать'}
        </button>
      </form>
    </main>
  )
}
