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
import Rpg from '@/pages/Rpg/Rpg'
import RpgModule from '@/pages/Rpg/RpgModule'
import RpgPlay from '@/pages/Rpg/RpgPlay'
import RpgPrompts from '@/pages/Rpg/RpgPrompts'
import RpgSettings from '@/pages/Rpg/RpgSettings'
import RpgPresets from '@/pages/Rpg/RpgPresets'
import BuildMode from '@/pages/Build/BuildMode'
import Login from '@/pages/Auth/Login'
import RequireAuth from '@/components/RequireAuth'
import ConfirmHost from '@/components/ConfirmDialog/ConfirmDialog'
import GenerationIndicator from '@/components/GenerationIndicator/GenerationIndicator'
import BuildIndicator from '@/components/BuildIndicator/BuildIndicator'
import RpgTurnIndicator from '@/components/GenerationIndicator/RpgTurnIndicator'
import TavernTurnIndicator from '@/components/GenerationIndicator/TavernTurnIndicator'
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
          <Route path="/game" element={<Rpg />} />
          <Route path="/game/prompts" element={<RpgPrompts />} />
          <Route path="/game/settings" element={<RpgSettings />} />
          {/* 没配 /rpg/presets 重定向：那批是给老书签用的，新页没有老书签 */}
          <Route path="/game/presets" element={<RpgPresets />} />
          <Route path="/game/module/:id" element={<RpgModule />} />
          <Route path="/game/play/:sessionId" element={<RpgPlay />} />
          <Route path="/rpg" element={<Navigate to="/game" replace />} />
          <Route path="/rpg/prompts" element={<Navigate to="/game/prompts" replace />} />
          <Route path="/rpg/settings" element={<Navigate to="/game/settings" replace />} />
          <Route path="/rpg/module/:id" element={<RpgModule />} />
          <Route path="/rpg/play/:sessionId" element={<RpgPlay />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/account" element={<Account />} />
          <Route path="/about" element={<About />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* 浮层药丸都挂在这儿，外层负责定位和堆叠。原先各自带 fixed bottom-5
          right-5，同时开两件事就会精确叠在一起——同一时刻只可能有一件事在跑
          的时候够不着，加了 RPG 和酒馆这两个就够得着了 */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
        <GenerationIndicator />
        <BuildIndicator />
        <RpgTurnIndicator />
        <TavernTurnIndicator />
      </div>
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
