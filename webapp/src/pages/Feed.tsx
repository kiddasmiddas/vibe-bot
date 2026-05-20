import { useCallback, useEffect, useRef, useState } from 'react'
import { getFeed, UnauthorizedError } from '../api/client'
import type { PostPreview } from '../api/types'
import { PostCard } from '../components/PostCard'
import { ErrorScreen } from '../components/ErrorScreen'
import { useTelegram } from '../hooks/useTelegram'
import styles from './Feed.module.css'

type LoadState = 'idle' | 'loading-initial' | 'loading-more' | 'error-unauthorized' | 'error-network' | 'done'

const SKELETON_COUNT = 6

export function Feed() {
  const { ready, hideBackButton } = useTelegram()

  const [items, setItems] = useState<PostPreview[]>([])
  // cursor читаем через setCursor(cur => ...) внутри IntersectionObserver,
  // чтобы не пересоздавать observer при каждом изменении.
  const [, setCursor] = useState<string | undefined>(undefined)
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const hasMoreRef = useRef(true)
  const loadStateRef = useRef<LoadState>('idle')
  const isFirstLoadDoneRef = useRef(false)

  // Синхронизируем ref с state, чтобы читать из IntersectionObserver без stale closure
  useEffect(() => {
    loadStateRef.current = loadState
  }, [loadState])

  useEffect(() => {
    ready()
    hideBackButton()
  }, [ready, hideBackButton])

  const loadMore = useCallback(async (currentCursor?: string) => {
    if (!hasMoreRef.current) return
    const isInitial = !isFirstLoadDoneRef.current

    setLoadState(isInitial ? 'loading-initial' : 'loading-more')

    try {
      const data = await getFeed(currentCursor)
      setItems((prev) => (isInitial ? data.items : [...prev, ...data.items]))

      if (data.next_cursor) {
        setCursor(data.next_cursor)
      } else {
        hasMoreRef.current = false
        setCursor(undefined)
      }
      setLoadState('done')
      isFirstLoadDoneRef.current = true
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setLoadState('error-unauthorized')
      } else {
        setLoadState('error-network')
      }
      hasMoreRef.current = false
    }
  }, [])

  // Первая загрузка
  useEffect(() => {
    void loadMore(undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Infinite scroll через IntersectionObserver
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0]
        if (
          entry?.isIntersecting &&
          hasMoreRef.current &&
          loadStateRef.current !== 'loading-more' &&
          loadStateRef.current !== 'loading-initial'
        ) {
          setCursor((cur) => {
            void loadMore(cur)
            return cur
          })
        }
      },
      { rootMargin: '200px' }
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  const handleRetry = () => {
    hasMoreRef.current = true
    isFirstLoadDoneRef.current = false
    setItems([])
    setCursor(undefined)
    void loadMore(undefined)
  }

  if (loadState === 'error-unauthorized') {
    return <ErrorScreen type="unauthorized" />
  }

  if (loadState === 'error-network' && items.length === 0) {
    return <ErrorScreen type="network" onRetry={handleRetry} />
  }

  const isInitialLoading = loadState === 'loading-initial'
  const isEmpty = loadState === 'done' && items.length === 0
  const isLoadingMore = loadState === 'loading-more'
  const isEnd = !hasMoreRef.current && loadState === 'done' && items.length > 0

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.kicker}>твой вайб - твои люди</p>
        <h1>Аллея креаторов</h1>
      </header>

      {isInitialLoading && (
        <div className={styles.grid} aria-busy="true" aria-label="Загрузка ленты">
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <div key={i} className={styles.skeletonCard} aria-hidden="true" />
          ))}
        </div>
      )}

      {isEmpty && (
        <div className={styles.empty}>
          <span className={styles.emptyIcon} aria-hidden="true">🎨</span>
          <h2 className={styles.emptyTitle}>Пока здесь пусто</h2>
          <p className={styles.emptyMessage}>
            Креаторы ещё не разместили свои посты. Заходите позже!
          </p>
        </div>
      )}

      {items.length > 0 && (
        <>
          <ul className={styles.grid} aria-label="Лента креаторов">
            {items.map((post) => (
              <li key={post.id}>
                <PostCard post={post} />
              </li>
            ))}
          </ul>

          {isLoadingMore && (
            <div className={styles.loadingMore} aria-label="Загрузка следующих постов">
              <div className={styles.spinner} aria-hidden="true" />
            </div>
          )}

          {isEnd && (
            <p className={styles.endOfFeed}>Вы дошли до конца ленты</p>
          )}
        </>
      )}

      {/* Sentinel для IntersectionObserver */}
      <div ref={sentinelRef} className={styles.sentinel} aria-hidden="true" />
    </main>
  )
}
