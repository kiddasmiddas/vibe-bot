import { Routes, Route, Navigate } from 'react-router-dom'
import { Feed } from './pages/Feed'
import { PostDetail } from './pages/PostDetail'
import { FeedList } from './pages/FeedList'
import { FeedPostDetail } from './pages/FeedPostDetail'
import { FeedCreate } from './pages/FeedCreate'

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Feed />} />
      <Route path="/post/:id" element={<PostDetail />} />
      <Route path="/feed" element={<FeedList />} />
      <Route path="/feed/new" element={<FeedCreate />} />
      <Route path="/feed/:id" element={<FeedPostDetail />} />
      {/* Fallback: любой неизвестный путь → на главную */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
