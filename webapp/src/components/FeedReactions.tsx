import { useState } from 'react'
import { setFeedReaction, removeFeedReaction, ApiError } from '../api/client'
import type { FeedReactions as FeedReactionsType } from '../api/types'
import styles from './FeedReactions.module.css'

interface ReactionButton {
  key: keyof FeedReactionsType
  emoji: string
  label: string
}

const REACTION_BUTTONS: ReactionButton[] = [
  { key: 'heart', emoji: '💚', label: 'Сердце' },
  { key: 'sparkle', emoji: '✨', label: 'Искры' },
  { key: 'cry', emoji: '😭', label: 'Плачу' },
  { key: 'eyes', emoji: '👀', label: 'Глаза' },
]

interface FeedReactionsProps {
  postId: number
  reactions: FeedReactionsType
  myReaction: string | null
}

export function FeedReactions({ postId, reactions, myReaction }: FeedReactionsProps) {
  const [counts, setCounts] = useState<FeedReactionsType>(reactions)
  const [active, setActive] = useState<string | null>(myReaction)
  const [busy, setBusy] = useState(false)

  const handleClick = async (key: keyof FeedReactionsType) => {
    if (busy) return
    setBusy(true)
    try {
      if (active === key) {
        const res = await removeFeedReaction(postId)
        setCounts(res.counts)
        setActive(null)
      } else {
        const res = await setFeedReaction(postId, key)
        setCounts(res.counts)
        setActive(res.my_reaction)
      }
    } catch (err) {
      if (!(err instanceof ApiError)) {
        // network errors — silently ignore for now
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.reactions} role="group" aria-label="Реакции">
      {REACTION_BUTTONS.map(({ key, emoji, label }) => {
        const isActive = active === key
        return (
          <button
            key={key}
            type="button"
            className={`${styles.reactionBtn} ${isActive ? styles.reactionBtnActive : ''}`}
            onClick={() => void handleClick(key)}
            disabled={busy}
            aria-pressed={isActive}
            aria-label={`${label}: ${counts[key]}`}
          >
            <span className={styles.emoji} aria-hidden="true">{emoji}</span>
            <span className={styles.count}>{counts[key]}</span>
          </button>
        )
      })}
    </div>
  )
}
