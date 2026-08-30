import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { BookOpen } from 'lucide-react'
import { authApi } from '@/api/client'
import { useAuthStore } from '@/store/authStore'

type Mode = 'login' | 'register'

export default function Login() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) return
    if (mode === 'register' && password !== confirm) {
      toast.error('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      const res = mode === 'login'
        ? await authApi.login(username.trim(), password)
        : await authApi.register(username.trim(), password)
      setAuth(res.token, res.user)
      navigate('/', { replace: true })
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || (mode === 'login' ? '登录失败' : '注册失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2 mb-8">
          <BookOpen className="w-8 h-8 text-primary" />
          <h1 className="text-2xl font-bold">NovelBot</h1>
        </div>

        <div className="rounded-xl border bg-card p-6">
          <div className="flex gap-1 mb-6 p-1 rounded-lg bg-muted">
            {(['login', 'register'] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  mode === m ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {m === 'login' ? '登录' : '注册'}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">用户名</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                className="w-full px-3 py-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder={mode === 'register' ? '2-32 位字母、数字、下划线或中文' : ''}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                className="w-full px-3 py-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder={mode === 'register' ? '至少 8 位' : ''}
              />
            </div>
            {mode === 'register' && (
              <div>
                <label className="block text-sm font-medium mb-1.5">确认密码</label>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  className="w-full px-3 py-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
            )}
            <button
              type="submit"
              disabled={loading || !username.trim() || !password}
              className="w-full py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {loading ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
