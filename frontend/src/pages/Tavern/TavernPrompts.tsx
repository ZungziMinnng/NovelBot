import { tavernPromptsApi } from '@/api/tavernPrompts'
import { useAuthStore } from '@/store/authStore'
import PromptOverridesEditor from '@/components/PromptOverridesEditor/PromptOverridesEditor'

export default function TavernPrompts({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const userId = useAuthStore(state => state.user?.id)

  return (
    <PromptOverridesEditor
      api={tavernPromptsApi}
      queryKey={['tavern-prompts', userId]}
      initialName="tavern_roleplay.jinja2"
      intro="修改仅对你的账号生效，适用于你的所有酒馆角色卡和对话。保存后从下一次调用开始使用，已有消息和摘要不会改写。 角色卡自己的系统指令与勾选的写作规则仍会一同生效。"
      variablesHint={<>用 {'{{ 变量名 }}'} 插入信息；保留需要的条件和循环。角色卡中的 {'{{user}}'} / {'{{char}}'} 与这里的变量不同，请参考默认模板的写法。</>}
      textareaId="tavern-prompt-content"
      onDirtyChange={onDirtyChange}
    />
  )
}
