import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Home from '@/pages/Home/Home'
import Editor from '@/pages/Editor/Editor'
import Characters from '@/pages/Characters/Characters'
import Outline from '@/pages/Outline/Outline'
import Settings from '@/pages/Settings/Settings'
import Admin from '@/pages/Admin/Admin'
import About from '@/pages/About/About'
import GenerationIndicator from '@/components/GenerationIndicator/GenerationIndicator'
import { useSettingsStore } from '@/store/settingsStore'

export default function App() {
  const theme = useSettingsStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/novel/:id" element={<Editor />} />
        <Route path="/novel/:id/characters" element={<Characters />} />
        <Route path="/novel/:id/outline" element={<Outline />} />
        <Route path="/novel/:id/data" element={<Admin />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Floating generation indicator shown on all pages except the active editor */}
      <GenerationIndicator />
      <Toaster position="top-right" toastOptions={{ duration: 4000 }} />
    </BrowserRouter>
  )
}
