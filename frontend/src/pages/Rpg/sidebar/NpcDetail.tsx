import { useEffect, useState } from 'react'
import { ChevronLeft, MapPin, Pencil, ScrollText, User, X } from 'lucide-react'
import { rpgApi, type RpgNpc, type RpgNpcHistoryEntry, type RpgMilestone, type RpgStatDef } from '@/api/client'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import RpgAvatar from '../RpgAvatar'
import ImageLightbox from '../ImageLightbox'
import StatBar from '../StatBar'
import { playSfx } from '../useSfx'
import Empty from './Empty'
import SummaryBlock from './SummaryBlock'

type Tab = 'profile' | 'history'

const TABS: { key: Tab; label: string; icon: typeof User }[] = [
  { key: 'profile', label: '资料', icon: User },
  { key: 'history', label: '经历', icon: ScrollText },
]

/**
 * 角色档案。只对已经见过面的人开，所以档案全文可以直接摊开——
 * 没见过的人连在侧栏列出都不该，更不会走到这里。
 *
 * 从前这是一张 portal 出来的全屏弹窗（NpcSheet），一点开剧情全被盖住。
 * 现在它就住在侧栏那一列里，顶掉名单、剧情照常看得见。所以这里**没有**
 * 遮罩和固定宽度：外面多宽它就多宽，320px 也得站得住。
 */
export default function NpcDetail({
  npc, relationDefs, state, notes, appearance, activity, history, activityLog,
  milestones, here, place, following,
  summary, onSaveSummary,
  onUnfollow, onBack, onDeleteNote, onDeleteAppearance, onDeleteActivity, onSaved,
}: {
  npc: RpgNpc
  relationDefs: RpgStatDef[]
  state: Record<string, number | boolean>
  /** GM 这一局记下的他的近况。键值都是模型自己起的，模组里没有 */
  notes: Record<string, string>
  /** 这一局被**永久改写掉**的外貌。{"胸部": "服丰元玉乳散后长出"}。
   *  它不是「这一局顺手记的一笔」——注入时它压过上面那段作者写的「看上去」，
   *  所以玩家发现她的样子和设定对不上时，答案在这儿 */
  appearance: Record<string, string>
  /** AI 调度替你不在场时她做的事记下的一句话。没勾「AI 调度」的人是空串 */
  activity: string
  /** 她这一局的经历，按发生顺序攒下来的。空数组 = 这一局还没发生过什么 */
  history: RpgNpcHistoryEntry[]
  /** 上面那句 activity 按时段留的底，最多 12 条。画在经历下面、**分开标题**：
   *  经历是玩出来的（每条都在正文里有原话），这一列是调度编的背景活动。
   *  玩家按一串「结束时段」时经历理所当然是空的，能看的只有这一列 */
  activityLog: RpgNpcHistoryEntry[]
  /** 整局的关系里程碑，**没按人筛过**：一条里程碑连着两个人，
   *  筛哪一头是这儿的事（见下面 myMilestones） */
  milestones: RpgMilestone[]
  /** 他此刻是不是和玩家在同一个地点 */
  here: boolean
  /** 他此刻在哪儿。**不是角色卡上的常驻地点**——有作息表的人是按时段走的，
   *  写常驻地点会让玩家跑过去扑空 */
  place: string
  /** 他是不是跟着你走。是的话页眉那个「就在你面前」换成「跟着你」加一个叉——
   *  那个叉是**唯一的解除入口**，打字认不出来的说法（「你走吧」以外的各种讲法）
   *  全靠它兜底 */
  following: boolean
  /** 和她那格的长期记忆：旧剧情溢出窗口时压成的一段话。空 = 还没溢出过，
   *  她的对话全都还在窗口里原样记着 */
  summary: string
  /** 改写那段记忆。空串 = 丢掉它 */
  onSaveSummary: (text: string) => Promise<void>
  /** 打发她走。点那个叉走这里 */
  onUnfollow: () => void
  /** 回名单。从前是「关掉弹窗」，现在是主从里的那个返回箭头 */
  onBack: () => void
  /** 划掉记错的一条。模型写下的持久事实，玩家得有个不读档的补救 */
  onDeleteNote: (key: string) => void
  /** 划掉一处被误改的外貌。同上的补救，但后果更重——不划掉她一直长着那样 */
  onDeleteAppearance: (key: string) => void
  /** 划掉那一句「最近在做什么」。同上的补救，但它是单独一句不是键值表 */
  onDeleteActivity: () => void
  /** 档案存完了。改的是模组里那张卡，所以父组件要顺手把角色列表也刷一下 */
  onSaved: (updated: RpgNpc) => void
}) {
  // 换一个人看时这个组件靠 key 重挂，所以一次挂载 = 一次打开
  useEffect(() => { playSfx('npc') }, [])

  const [draft, setDraft] = useState<RpgNpc | null>(null)
  const [viewing, setViewing] = useState(false)
  /** 资料是模组作者写死的，经历是这一局长出来的。摊在一页上翻到后面全是
   *  模型写的字，分不清哪句是设定哪句是这一局发生的——和小说侧角色页同一个分法 */
  const [tab, setTab] = useState<Tab>('profile')

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」 */
  const body = () => ({
    // 名字清空不算「存不下去」：这一栏从前就是这个规矩——空了退回原来的名字，
    // 免得把一张卡存成没有名字的东西。所以这里没有 blocked 那一态
    name: (draft?.name || '').trim() || npc.name,
    age: draft?.age,
    description: draft?.description,
    persona: draft?.persona,
    appearance: draft?.appearance,
    profile_sections: draft?.profile_sections,
  })

  /** 改哪一格就存哪一格。**存完不退出编辑态**——从前那版 `save` 里那句
   *  `setDraft(null)` 是给按按钮的人一个「存好了」的回执，自动保存不需要回执，
   *  半句话没写完就被弹出去反而更烦。退不退由用户点「收起」决定 */
  const autosave = useFormAutosave(
    draft ? { id: npc.id, body: body() } : null,
    draft !== null,
    async ({ id, body }) => { onSaved(await rpgApi.npcs.update(id, body)) },
  )

  /** 收起编辑态。没存成的时候不能收：收了就等于把改动默默扔掉，
   *  而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) setDraft(null) }

  /** 切页。改到一半切走等于把改动默默扔掉，所以先按「收起」那套规矩存一次，
   *  存不下去就留在原地 */
  const switchTab = async (next: Tab) => {
    if (next === tab) return
    if (draft && !(await autosave.flush())) return
    setDraft(null)
    setTab(next)
  }

  const sections = Object.entries(npc.profile_sections || {}).filter(([, text]) => (text || '').trim())
  const noteRows = Object.entries(notes || {}).filter(([, text]) => (text || '').trim())
  // 被改写的外貌。**名字不跟 noteRows 合并**：这两样虽然都是模型写的，但那一块
  // 的开头写着「模型在这一局里记下的，和模组原本的设定分开」——而外貌改写干的
  // 恰恰是**盖掉**模组原本的设定，混在一起玩家就分不清哪条是覆盖、哪条是补充
  const appearanceRows = Object.entries(appearance || {}).filter(([, text]) => (text || '').trim())
  const visibleRelationDefs = npc.relation_enabled === false
    ? []
    : npc.relation_stat_names?.length
      ? relationDefs.filter(def => npc.relation_stat_names.includes(def.name))
      : relationDefs
  // 新的排在上面：这一列多半只看得见头几行，而玩家想知道的是「她最近怎么了」
  const historyRows = [...(history || [])].reverse()
  const activityRows = [...(activityLog || [])].reverse()
  // 结算时两侧的名字已经归一成名册上的写法了，所以这里能按名字直接挑
  const myMilestones = (milestones || []).filter(m => m.a === npc.name || m.b === npc.name)

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* 和编辑器详情列一样的固定页眉：返回、身份、随内容滚动时不跑掉 */}
      <div className="shrink-0 border-b border-border/60 px-3 py-2.5 flex items-center gap-2">
        <button
          onClick={onBack}
          title="回名单"
          className="p-1 rounded hover:bg-muted shrink-0"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        {/* 立绘是竖图，方头像里只露得出脸，给条看原图的路 */}
        {npc.avatar_url ? (
          <button onClick={() => setViewing(true)} title="看立绘" className="shrink-0">
            <RpgAvatar name={npc.name} url={npc.avatar_url} size="md" />
          </button>
        ) : (
          <RpgAvatar name={npc.name} url={npc.avatar_url} size="md" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold truncate">{npc.name}</p>
          <p className="text-xs text-muted-foreground flex items-center gap-1 truncate">
            <MapPin className="w-3 h-3 shrink-0" />
            {place || '行踪不定'}
            {/* 跟着你的时候不说「就在你面前」：那句话是对的但没信息量，
                玩家真正要知道的是「她为什么一直在这儿」 */}
            {here && !following && <span className="text-primary shrink-0">· 就在你面前</span>}
          </p>
        </div>
        {following && (
          // 小块是状态、叉是入口，所以它们挂在页眉这一行上而不是地点那行里：
          // 那是可点的东西，塞进 truncate 的 <p> 里会被截掉
          <span className="shrink-0 flex items-center gap-0.5">
            <span className="text-[10px] px-1 py-0.5 rounded
              bg-cyan-500/15 text-cyan-700 dark:text-cyan-300">
              跟着你
            </span>
            <button
              onClick={onUnfollow}
              title="别跟着了"
              className="p-0.5 rounded text-muted-foreground/60 hover:bg-muted hover:text-foreground shrink-0"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        )}
        {/* 笔和「立即保存」只在资料页出现：经历是结算写的，这儿没得改 */}
        {tab !== 'profile' ? null : draft ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={autosave.flush}
              className="text-xs px-2 py-1 rounded-lg bg-primary text-primary-foreground hover:opacity-90"
            >
              立即保存
            </button>
            <button
              onClick={close}
              className="text-xs px-2 py-1 rounded-lg border text-muted-foreground hover:bg-muted"
            >
              收起
            </button>
          </div>
        ) : (
          <button
            onClick={() => setDraft(npc)}
            title="改这个人的档案"
            className="p-1 rounded text-muted-foreground hover:bg-muted hover:text-foreground shrink-0"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* 比外面那排主标签轻一档：那排是「侧栏在看什么」，这排只管这一个人的档案，
          长一样重会让人以为自己跳出角色页了 */}
      <div className="flex shrink-0 border-b border-border/60 px-3">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => switchTab(key)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs border-b-2 -mb-px transition-colors
              ${tab === key
                ? 'border-primary text-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'history' ? (
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {/* 排在最上面：下面那两块是「记录」，只给人看；这一块是模型每轮真正
              读到的那段话。玩家问「她怎么忘了这事」时该先看的就是它 */}
          <SummaryBlock
            title="她记得的"
            hint="旧剧情压成的一段话，只在她在你跟前时喂给模型。改它等于改她的记忆"
            empty="还没压过：你们说过的话都还在窗口里，她原样记着。"
            text={summary}
            onSave={onSaveSummary}
          />

          {myMilestones.length > 0 && (
            // 转折单独摊在最上面、不混进下面那条时间线：它是**这段关系**的事，
            // 一条连着两个人，而下面每一条都只关于她一个人
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">关系的转折</p>
              {myMilestones.map((m, i) => (
                <div key={i} className="flex items-start gap-2 text-sm leading-relaxed">
                  <span className="shrink-0 mt-0.5 text-[10px] px-1.5 py-0.5 rounded
                    bg-primary/15 text-primary font-medium">
                    {m.type}
                  </span>
                  <p className="flex-1">
                    {m.content}
                    <span className="ml-1.5 text-xs text-muted-foreground/70">第 {m.day} 天</span>
                  </p>
                </div>
              ))}
            </div>
          )}

          {historyRows.length > 0 ? (
            <div className="space-y-2.5">
              {historyRows.map((row, i) => (
                <div key={i} className="border-l-2 border-border pl-3">
                  <p className="text-[11px] text-muted-foreground">
                    第 {row.day} 天{row.slot ? ` · ${row.slot}` : ''}
                  </p>
                  <p className="text-sm leading-relaxed">{row.content}</p>
                </div>
              ))}
            </div>
          ) : (
            // 没有「生成一份」的按钮：经历是玩出来的，补一份等于让模型凭空编她的过去
            <Empty>
              {myMilestones.length > 0
                ? '除此之外还没记下她别的经历。'
                : activityRows.length > 0
                  // 这一格最容易让人以为是 bug：玩家按了一串「结束时段」，下面
                  // 那条流水一直在长、这儿却空着。说清两列各归谁写
                  ? '这一局还没和她一起经历什么。只有你在场的那些回合才会写在这儿。'
                  : '这一局还没记下她的事。接着玩，结算时会把她经历过的写在这儿。'}
            </Empty>
          )}

          {activityRows.length > 0 && (
            // 单独一块、标题写明是推算的：混进上面那条时间线会让「玩出来的事」
            // 和「模型替她编的背景」看着一样真，而只有上面那些过了正文取证
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">你不在的时候</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground/70">
                AI 调度按她的人设推的，没有正文依据，也不会喂给模型
              </p>
              {activityRows.map((row, i) => (
                <div key={i} className="border-l-2 border-dashed border-border/60 pl-3">
                  <p className="text-[11px] text-muted-foreground">
                    第 {row.day} 天{row.slot ? ` · ${row.slot}` : ''}
                  </p>
                  <p className="text-sm leading-relaxed text-muted-foreground">{row.content}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : draft ? (
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {/* 常驻不折叠。玩家在游玩界面里点开的是「这一局的她」，很容易以为
              改动只影响这一局——实际改的是模组那张卡，别的存档、以后每一局
              都会跟着变，而且没有撤销 */}
          <p className="text-xs leading-relaxed rounded-lg px-2.5 py-2
            bg-rose-500/10 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500/30">
            改的是模组档案，所有存档和以后每一局都会变
          </p>
          {/* 这一列最窄处只有 320px，页眉那一行塞不下状态字，所以它落在正文顶上。
              紧接着上面那条红线：改一笔就落一笔，正是那句话最该被看见的时候 */}
          <SaveBadge state={autosave.state} blocked="这一份还存不下去" onRetry={autosave.flush} />
          <Field label="名字" value={draft.name} rows={1}
            onChange={v => setDraft({ ...draft, name: v })} />
          <Field label="一句话介绍" value={draft.description}
            onChange={v => setDraft({ ...draft, description: v })} />
          <Field label="年龄" value={draft.age} rows={1}
            onChange={v => setDraft({ ...draft, age: v })} />
          <Field label="看上去" value={draft.appearance}
            onChange={v => setDraft({ ...draft, appearance: v })} />
          {appearanceRows.length > 0 && (
            // 这一栏现在**改不动她**了：模型每轮看到的是下面这几条压过它。
            // 不说的话，玩家在这儿把「平坦」改成「丰满」、照样看见模型写「平坦」，
            // 会以为改动没保存或者游戏坏了。真正该去的地方是资料页那几条
            <p className="text-xs leading-relaxed rounded-lg px-2.5 py-2
              bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/30">
              这一局里她的外貌已经被改写过（
              {appearanceRows.map(([key]) => key).join('、')}
              ），那几条会压过这一栏。要让她变回这里写的样子，先去资料页把它们划掉。
            </p>
          )}
          <Field label="性格" value={draft.persona}
            onChange={v => setDraft({ ...draft, persona: v })} />
          {/* 只改内容不改分栏名：加栏删栏是模组页那边的事，这儿是游玩途中
              顺手改一笔，别把整张卡的结构也放开 */}
          {Object.entries(draft.profile_sections || {}).map(([key, text]) => (
            <Field
              key={key}
              label={key}
              value={text}
              onChange={v => setDraft({
                ...draft,
                profile_sections: { ...draft.profile_sections, [key]: v },
              })}
            />
          ))}
        </div>
      ) : (
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {visibleRelationDefs.length > 0 && (
          <div className="space-y-2">
            {visibleRelationDefs.map(def => (
              <StatBar
                key={def.name}
                def={def}
                value={Number(state?.[def.name] ?? npc.initial_state?.[def.name] ?? def.initial)}
              />
            ))}
          </div>
        )}

        {npc.description && (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{npc.description}</p>
        )}

        {npc.age && <Block title="年龄">{npc.age}</Block>}
        {npc.appearance && <Block title="看上去">{npc.appearance}</Block>}

        {appearanceRows.length > 0 && (
          // 紧贴上面那段「看上去」，因为它干的正是**推翻**那一段：
          // 药剂改造、断手、毁容——这一局里永远回不去的变化。模型每轮看到的是
          // 这两段拼在一起、且以后者为准，玩家也该看到同一个顺序。
          //
          // 样式跟下面「这一局记下的」一致（都是模型写的，会出错），不并进那一块：
          // 那一块说的是「作者没写过、这一局补记的」，而这一块是「作者写过、
          // 但已经不作数了」，两句话正好相反
          <div className="border-l-2 border-amber-500/50 pl-3">
            <p className="text-xs font-medium text-amber-700 dark:text-amber-300">外貌已被改写</p>
            <p className="text-[11px] text-muted-foreground/70 mb-2">
              以这里为准，上面那段「看上去」已经不作数了
            </p>
            <div className="space-y-1">
              {appearanceRows.map(([key, text]) => (
                <div key={key} className="group flex items-start gap-2 text-sm leading-relaxed">
                  <p className="flex-1">
                    <span className="text-muted-foreground">{key}</span>
                    <span className="mx-1.5 text-muted-foreground/50">·</span>
                    {String(text)}
                  </p>
                  <button
                    onClick={() => onDeleteAppearance(key)}
                    title="划掉这条。划掉后她又变回模组里写的那个样子"
                    className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
        {npc.persona && <Block title="性格">{npc.persona}</Block>}
        {sections.map(([key, text]) => (
          <Block key={key} title={key}>{text}</Block>
        ))}

        {(noteRows.length > 0 || activity) && (
          // 刻意和上面那几块长得不一样：这些是模型边玩边写的，会出错，
          // 玩家得一眼看出来它不是模组作者写的设定，否则骂错人
          <div className="border-l-2 border-primary/40 pl-3">
            <p className="text-xs font-medium text-muted-foreground">这一局记下的</p>
            <p className="text-[11px] text-muted-foreground/70 mb-2">模型在这一局里记下的，和模组原本的设定分开</p>
            <div className="space-y-1">
              {/* 「最近」排在近况前面：它是这个人此刻的处境，近况是具体某一项 */}
              {activity && (
                <div className="group flex items-start gap-2 text-sm leading-relaxed">
                  <p className="flex-1">
                    <span className="text-muted-foreground">最近</span>
                    <span className="mx-1.5 text-muted-foreground/50">·</span>
                    {activity}
                  </p>
                  <button
                    onClick={onDeleteActivity}
                    title="划掉这句。她还是会继续自己过日子"
                    className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
              {noteRows.map(([key, text]) => (
                <div key={key} className="group flex items-start gap-2 text-sm leading-relaxed">
                  <p className="flex-1">
                    <span className="text-muted-foreground">{key}</span>
                    <span className="mx-1.5 text-muted-foreground/50">·</span>
                    {String(text)}
                  </p>
                  <button
                    onClick={() => onDeleteNote(key)}
                    title="划掉这条"
                    className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      )}

      {viewing && npc.avatar_url && (
        <ImageLightbox url={npc.avatar_url} alt={npc.name} onClose={() => setViewing(false)} />
      )}
    </div>
  )
}

function Block({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{title}</p>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{children}</p>
    </div>
  )
}

/** 编辑态的一格。一律 textarea：这一列最宽 520，长句子用 input 只能看见一行 */
function Field({ label, value, rows = 3, onChange }: {
  label: string
  value: string
  rows?: number
  onChange: (next: string) => void
}) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{label}</p>
      <textarea
        value={value || ''}
        rows={rows}
        onChange={e => onChange(e.target.value)}
        className="w-full text-sm leading-relaxed rounded-lg border bg-background px-2 py-1.5
          resize-y focus:outline-none focus:ring-1 focus:ring-primary/40"
      />
    </div>
  )
}
