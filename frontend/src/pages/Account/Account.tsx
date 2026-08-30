import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, Save } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi } from '@/api/client'
import { useAuthStore } from '@/store/authStore'

export default function Account() {
  const navigate = useNavigate()
  const authUser = useAuthStore((s) => s.user)
  const setAuthUser = useAuthStore((s) => s.setUser)

  const [username, setUsername] = useState(authUser?.username ?? '')
  const [savingName, setSavingName] = useState(false)

  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  const handleSaveUsername = async () => {
    const name = username.trim()
    if (!name) {
      toast.error('用户名不能为空')
      return
    }
    if (name === authUser?.username) {
      toast('用户名未变化')
      return
    }
    setSavingName(true)
    try {
      const u = await authApi.updateMe({ username: name })
      setAuthUser(u)
      toast.success('用户名已修改')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '修改失败')
    } finally {
      setSavingName(false)
    }
  }

  const handleSavePassword = async () => {
    if (!oldPassword) {
      toast.error('请填入旧密码')
      return
    }
    if (newPassword.length < 8) {
      toast.error('新密码至少 8 位')
      return
    }
    if (newPassword !== confirmPassword) {
      toast.error('两次输入的新密码不一致')
      return
    }
    setSavingPassword(true)
    try {
      await authApi.updateMe({ old_password: oldPassword, new_password: newPassword })
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success('密码已修改')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '修改失败')
    } finally {
      setSavingPassword(false)
    }
  }

  const inputCls = 'w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring'

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">用户设置</h1>
      </header>

      <main className="w-full max-w-xl mx-auto px-5 py-8 space-y-8">
        <section>
          <h2 className="font-semibold text-base mb-2">修改用户名</h2>
          <p className="text-xs text-muted-foreground mb-4">2-32 位字母、数字、下划线或中文。</p>
          <div className="space-y-3">
            <input
              value={username}
              onChange={e => setUsername(e.target.value)}
              className={inputCls}
              placeholder="用户名"
              maxLength={32}
            />
            <button
              onClick={handleSaveUsername}
              disabled={savingName}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
            >
              {savingName ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              保存用户名
            </button>
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-base mb-2">修改密码</h2>
          <p className="text-xs text-muted-foreground mb-4">需先填入旧密码验证身份，新密码至少 8 位。</p>
          <div className="space-y-3">
            <input
              type="password"
              value={oldPassword}
              onChange={e => setOldPassword(e.target.value)}
              className={inputCls}
              placeholder="旧密码"
              autoComplete="current-password"
            />
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              className={inputCls}
              placeholder="新密码（至少 8 位）"
              autoComplete="new-password"
            />
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              className={inputCls}
              placeholder="确认新密码"
              autoComplete="new-password"
            />
            <button
              onClick={handleSavePassword}
              disabled={savingPassword}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
            >
              {savingPassword ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              修改密码
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}
