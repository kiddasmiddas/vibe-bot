import styles from './ErrorScreen.module.css'

interface ErrorScreenProps {
  type: 'unauthorized' | 'network' | 'not-found' | 'generic'
  onRetry?: () => void
}

const ERROR_CONTENT = {
  unauthorized: {
    icon: '🔒',
    title: 'Нет доступа',
    message: 'Откройте «Аллею креаторов» через кнопку в боте @vibebot, чтобы продолжить.',
  },
  network: {
    icon: '📡',
    title: 'Ошибка соединения',
    message: 'Не удалось загрузить данные. Проверьте подключение к интернету и попробуйте ещё раз.',
  },
  'not-found': {
    icon: '🔍',
    title: 'Пост не найден',
    message: 'Этот пост удалён, истёк или находится на модерации.',
  },
  generic: {
    icon: '⚠️',
    title: 'Что-то пошло не так',
    message: 'Произошла непредвиденная ошибка. Попробуйте обновить страницу.',
  },
} as const

export function ErrorScreen({ type, onRetry }: ErrorScreenProps) {
  const content = ERROR_CONTENT[type]

  return (
    <div className={styles.container} role="alert">
      <span className={styles.icon} aria-hidden="true">
        {content.icon}
      </span>
      <h2 className={styles.title}>{content.title}</h2>
      <p className={styles.message}>{content.message}</p>
      {onRetry && type !== 'unauthorized' && type !== 'not-found' && (
        <button className={styles.retryButton} onClick={onRetry}>
          Попробовать снова
        </button>
      )}
    </div>
  )
}
