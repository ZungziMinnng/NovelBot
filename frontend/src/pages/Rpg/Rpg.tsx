import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Plus, Pencil, Trash2, Loader2, Dices, Users, BookMarked, Swords, ScrollText } from 'lucide-react'
import { rpgApi, type RpgModule } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import SpotlightCard from '@/components/SpotlightCard/SpotlightCard'
import { PANEL } from './rpgUi'

export default function Rpg() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: modules = [], isLoading } = useQuery({
    queryKey: ['rpg-modules'],
    queryFn: rpgApi.modules.list,
  })

  const handleDelete = async (module: RpgModule) => {
    if (!await confirmDialog({
      title: `确认删除模组「${module.name}」？`,
      detail: '它的全部局、消息、存档、NPC 和世界书词条会一起删掉，不可恢复。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.modules.delete(module.id)
      qc.invalidateQueries({ queryKey: ['rpg-modules'] })
    } catch {
      toast.error('删除模组失败')
    }
  }

  const create = async () => {
    try {
      const created = await rpgApi.modules.create({ name: '未命名模组' })
      qc.invalidateQueries({ queryKey: ['rpg-modules'] })
      navigate(`/rpg/module/${created.id}`)
    } catch {
      toast.error('创建模组失败')
    }
  }

  return (
    <div className="mode-rpg min-h-screen bg-background relative">
      <div className="fixed inset-0 z-0 opacity-[0.13] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#6d3ab0" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/')} className="p-2 rounded-md hover:bg-muted" title="返回模式选择">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Dices className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">RPG</h1>
        <button
          onClick={() => navigate('/rpg/prompts')}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border
            text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="改写给模型的指令：主持人、裁决、结算、帮我想想"
        >
          <ScrollText className="w-3.5 h-3.5" /> 提示词
        </button>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-5xl mx-auto px-6 py-12 space-y-8">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold mb-1.5">想去哪个世界？</h2>
            <p className="text-sm text-muted-foreground">
              {modules.length === 0
                ? '还没有模组。模组是一份可以反复开局的剧本：世界观、开场、NPC 和难度都写在里面。'
                : `${modules.length} 个模组`}
            </p>
          </div>
          <button
            onClick={create}
            className="flex items-center gap-1.5 text-sm rounded-lg px-4 py-2 shrink-0
              bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20 transition-colors"
          >
            <Plus className="w-4 h-4" /> 新建模组
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : modules.length === 0 ? (
          <button
            onClick={create}
            className="w-full rounded-xl border border-dashed border-violet-500/30 py-20 text-center
              hover:bg-violet-500/5 transition-colors group"
          >
            <Dices className="w-10 h-10 mx-auto mb-3 text-violet-500/40 group-hover:text-violet-500/70 transition-colors" />
            <p className="text-sm text-muted-foreground">点这里写第一个模组</p>
          </button>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2">
            {modules.map(module => (
              <SpotlightCard
                key={module.id}
                spotlightColor="rgba(167, 139, 250, 0.14)"
                className={`${PANEL} backdrop-blur-sm hover:border-primary/50 transition-colors`}
              >
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-violet-500/70" />
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/rpg/module/${module.id}`)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault(); navigate(`/rpg/module/${module.id}`)
                    }
                  }}
                  className="pl-7 pr-5 py-5 flex flex-col gap-4 h-full cursor-pointer focus:outline-none"
                >
                  <div className="flex items-start gap-3.5">
                    <ModuleCover name={module.name} url={module.cover_url} />
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold truncate">{module.name}</p>
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-3">
                        <span className="flex items-center gap-1" title="NPC">
                          <Users className="w-3 h-3" />{module.npc_count}
                        </span>
                        <span className="flex items-center gap-1" title="世界书词条">
                          <BookMarked className="w-3 h-3" />{module.entry_count}
                        </span>
                        {module.session_count > 0 && (
                          <span className="flex items-center gap-1 text-primary" title="进行中的局">
                            <Swords className="w-3 h-3" />{module.session_count}
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={e => { e.stopPropagation(); navigate(`/rpg/module/${module.id}`) }}
                        className="p-1.5 rounded hover:bg-muted"
                        title="编辑模组"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(module) }}
                        className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                        title="删除"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* creator_note 的用处就在这里：给人看的备注，后端永不发给模型 */}
                  <p className="text-xs text-muted-foreground/80 leading-relaxed line-clamp-2 min-h-[2rem]">
                    {module.creator_note || '（没有写介绍）'}
                  </p>
                </div>
              </SpotlightCard>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

/** 模组封面。没传图时用名字首字 + 紫色渐变占位，保证列表页不出现空洞 */
function ModuleCover({ name, url }: { name: string; url: string }) {
  if (url) {
    return <img src={url} alt={name} className="w-14 h-14 rounded-xl object-cover ring-1 ring-violet-500/25 shrink-0" />
  }
  return (
    <div
      className="w-14 h-14 text-lg rounded-xl shrink-0 flex items-center justify-center font-semibold
        bg-gradient-to-br from-violet-500/35 to-indigo-700/25 text-violet-900 dark:text-violet-200
        ring-1 ring-violet-500/25"
    >
      {name.trim().slice(0, 1) || '?'}
    </div>
  )
}
