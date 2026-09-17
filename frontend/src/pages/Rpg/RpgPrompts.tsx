import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ScrollText } from 'lucide-react'
import { rpgPromptsApi } from '@/api/rpgPrompts'
import { useAuthStore } from '@/store/authStore'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import PromptOverridesEditor from '@/components/PromptOverridesEditor/PromptOverridesEditor'

export default function RpgPrompts() {
  const navigate = useNavigate()
  const userId = useAuthStore(state => state.user?.id)
  // 编辑器内部算的 dirty 提上来，返回按钮要用它拦一下
  const [dirty, setDirty] = useState(false)

  const goBack = async () => {
    if (dirty && !await confirmDialog({ title: '提示词尚未保存，仍要离开？', confirmText: '离开' })) return
    navigate('/game')
  }

  return (
    <div className="mode-game min-h-screen bg-background relative">
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={goBack} className="p-2 rounded-md hover:bg-muted" title="返回游戏">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ScrollText className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">游戏提示词</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-8">
        <PromptOverridesEditor
          api={rpgPromptsApi}
          queryKey={['rpg-prompts', userId]}
          initialName="rpg_gm.jinja2"
          intro="修改仅对你的账号生效，适用于你的所有游戏模组和存档。保存后从下一轮开始使用，已有的叙事和存档不会改写。 模组自己的叙事风格、世界观和世界书词条仍会一同注入。"
          variablesHint={<>用 {'{{ 变量名 }}'} 插入信息；保留需要的条件和循环。这里写下的变量名必须是下面这些，写错会在保存时就报错。</>}
          textareaId="rpg-prompt-content"
          introWhilePending
          onDirtyChange={setDirty}
        />
      </main>
    </div>
  )
}
