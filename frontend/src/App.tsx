import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Landing from '@/pages/Landing/Landing'
import Home from '@/pages/Home/Home'
import NewNovel from '@/pages/Home/NewNovel'
import Editor from '@/pages/Editor/Editor'
import Characters from '@/pages/Characters/Characters'
import Outline from '@/pages/Outline/Outline'
import Locations from '@/pages/Locations/Locations'
import Notes from '@/pages/Notes/Notes'
import Settings from '@/pages/Settings/Settings'
import Account from '@/pages/Account/Account'
import Admin from '@/pages/Admin/Admin'
import About from '@/pages/About/About'
import Rules from '@/pages/Rules/Rules'
import Tavern from '@/pages/Tavern/Tavern'
import TavernCard from '@/pages/Tavern/TavernCard'
import TavernChat from '@/pages/Tavern/TavernChat'
import TavernSettings from '@/pages/Tavern/TavernSettings'
import BuildMode from '@/pages/Build/BuildMode'
import Login from '@/pages/Auth/Login'
import RequireAuth from '@/components/RequireAuth'
import ConfirmHost from '@/components/ConfirmDialog/ConfirmDialog'
import GenerationIndicator from '@/components/GenerationIndicator/GenerationIndicator'
import BuildIndicator from '@/components/BuildIndicator/BuildIndicator'
import { useSettingsStore } from '@/store/settingsStore'
import { getThemeById } from '@/lib/themes'

export default function App() {
  const theme = useSettingsStore((s) => s.theme)
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)

  useEffect(() => {
    const root = document.documentElement
    const activeThemeId = nsfwMode ? 'nsfw' : theme
    const def = getThemeById(activeThemeId)
    root.setAttribute('data-theme', def.id)
    if (def.base === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme, nsfwMode])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Landing />} />
          <Route path="/novels" element={<Home />} />
          <Route path="/novel/new" element={<NewNovel />} />
          <Route path="/novel/:id" element={<Editor />} />
          <Route path="/novel/:id/build" element={<BuildMode />} />
          <Route path="/novel/:id/characters" element={<Characters />} />
          <Route path="/novel/:id/outline" element={<Outline />} />
          <Route path="/novel/:id/locations" element={<Locations />} />
          <Route path="/novel/:id/notes" element={<Notes />} />
          <Route path="/novel/:id/data" element={<Admin />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/tavern" element={<Tavern />} />
          <Route path="/tavern/settings" element={<TavernSettings />} />
          <Route path="/tavern/card/:id" element={<TavernCard />} />
          <Route path="/tavern/chat/:sessionId" element={<TavernChat />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/account" element={<Account />} />
          <Route path="/about" element={<About />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <GenerationIndicator />
      <BuildIndicator />
      <ConfirmHost />
      {/* 跟着主题走：默认 toast 是写死的白底，换到深色主题就成了一块亮斑 */}
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          className: '!bg-card !text-card-foreground !border !border-border !shadow-lg !text-sm',
          success: { iconTheme: { primary: 'hsl(var(--primary))', secondary: 'hsl(var(--card))' } },
        }}
      />
    </BrowserRouter>
  )
}
