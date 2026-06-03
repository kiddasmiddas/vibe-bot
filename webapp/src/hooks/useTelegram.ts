import { useCallback, useEffect, useRef } from 'react'

// Объявление глобального window.Telegram — SDK подключён через <script> в index.html
declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp
    }
  }
}

interface ThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
}

interface BackButtonInstance {
  isVisible: boolean
  show(): void
  hide(): void
  onClick(fn: () => void): void
  offClick(fn: () => void): void
}

interface TelegramUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
}

interface InitDataUnsafe {
  user?: TelegramUser
  query_id?: string
  auth_date?: number
  hash?: string
}

interface TelegramWebApp {
  initData: string
  initDataUnsafe?: InitDataUnsafe
  themeParams: ThemeParams
  ready(): void
  expand(): void
  close(): void
  openTelegramLink(url: string): void
  BackButton: BackButtonInstance
}

function getTg(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null
}

interface UseTelegramResult {
  initData: string | null
  /** Telegram-id текущего пользователя (из initDataUnsafe.user.id). null вне Telegram. */
  currentUserId: number | null
  themeParams: ThemeParams
  ready: () => void
  openTelegramLink: (url: string) => void
  showBackButton: (onClick: () => void) => void
  hideBackButton: () => void
}

export function useTelegram(): UseTelegramResult {
  const backClickHandlerRef = useRef<(() => void) | null>(null)

  const ready = useCallback(() => {
    const tg = getTg()
    if (tg) {
      tg.ready()
      tg.expand()
    }
  }, [])

  const openTelegramLink = useCallback((url: string) => {
    const tg = getTg()
    // openTelegramLink в TWA SDK принимает только https://t.me/* — для других
    // ссылок (или вне Telegram) фолбэк на обычное окно.
    const isTelegramLink = url.startsWith('https://t.me/') || url.startsWith('t.me/')
    if (tg && isTelegramLink) {
      tg.openTelegramLink(url)
    } else {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }, [])

  const showBackButton = useCallback((onClick: () => void) => {
    const tg = getTg()
    if (!tg) return

    // Снять предыдущий обработчик если был
    if (backClickHandlerRef.current) {
      tg.BackButton.offClick(backClickHandlerRef.current)
    }
    backClickHandlerRef.current = onClick
    tg.BackButton.onClick(onClick)
    tg.BackButton.show()
  }, [])

  const hideBackButton = useCallback(() => {
    const tg = getTg()
    if (!tg) return
    if (backClickHandlerRef.current) {
      tg.BackButton.offClick(backClickHandlerRef.current)
      backClickHandlerRef.current = null
    }
    tg.BackButton.hide()
  }, [])

  // Очистка при размонтировании
  useEffect(() => {
    return () => {
      const tg = getTg()
      if (tg && backClickHandlerRef.current) {
        tg.BackButton.offClick(backClickHandlerRef.current)
      }
    }
  }, [])

  const tg = getTg()
  const rawUserId = tg?.initDataUnsafe?.user?.id
  const currentUserId =
    typeof rawUserId === 'number' && Number.isFinite(rawUserId) ? rawUserId : null
  return {
    initData: tg?.initData && tg.initData.length > 0 ? tg.initData : null,
    currentUserId,
    themeParams: tg?.themeParams ?? {},
    ready,
    openTelegramLink,
    showBackButton,
    hideBackButton,
  }
}
