import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Dices, ImagePlus, Loader2, RefreshCw, Sparkles, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgApi, type RpgNpc, type RpgImageConfig, type RpgLocation } from '@/api/client'
import ImageLightbox from './ImageLightbox'
import ImageSettingsFields from './ImageSettingsFields'
import { mergeImageConfig } from './imageConfig'
import { frameOf } from './imageFrames'
import { DEFAULT_POSE } from './imagePoses'
import { INPUT } from './rpgUi'

/** 外貌那几栏拼成出图提示词。Z-Image 吃中文自然语言，不用翻成英文标签。
 *
 *  外貌之后紧跟**常驻地点**（地点名 + 地点表里那段描述）——不带地点的话，
 *  模型会把人摆在白墙或者摄影棚幕布前面。地点描述是给模型读剧情用的，
 *  里头「宗门里的人都怕她」这类非视觉句子也会跟着进去，删不删交给用户：
 *  整句是预填进弹窗那个可编辑文本框的，看得见。
 *
 *  再往后是模组题材、出图设置里的画风和补充词——**题材那一段很要紧**：
 *  不带的话玄幻模组的 NPC 会被画成一身现代衣服。
 *  最后是姿势（出图设置里选，默认站姿全身像）：只给外貌描述的话模型多半只画个
 *  大头照，不是立绘。用 `??` 取默认是有意的，见 imagePoses.ts 里 DEFAULT_POSE 那段。
 *
 *  `cfg` 收的是**合并后**的那一份（模组打底 + 这个角色的覆写，见 imageConfig.ts）：
 *  这里不必知道设置分了几层，拿到什么就拼什么。 */
function buildPrompt(
  npc: RpgNpc, genre: string, cfg: RpgImageConfig, place?: RpgLocation,
): string {
  // 外貌只有顶层这一栏：分栏里的外貌键会被后端读时归一进它（见
  // normalize_profile_sections），所以这里不必再看 profile_sections
  const parts = [(npc.appearance || '').trim()].filter(Boolean)
  if (!parts.length && npc.description.trim()) parts.push(npc.description.trim())
  // 地点表里没这一条时落回 npc.location 这个名字本身。常驻地点那一栏是从
  // 地点表里挑的，正常对得上，但模组是可以先填人后删地点的
  const scene = place
    ? [place.name, place.description]
    : [npc.location]
  // 画幅那句构图 tag（standing,full_body / game_cg,scenery …）也拼进去：它管的是
  // 「这张图是竖立绘还是横 CG」，和 pose 的取景略有重叠但不冗余——横幅 CG 的
  // game_cg,scenery 是 pose 给不出的。尺寸那两个数字不在这里，由调用方回表查了
  // 单独传进出图请求
  const tail = [...scene, genre, cfg.style, cfg.extra, cfg.pose ?? DEFAULT_POSE,
    frameOf(cfg.frame).tag]
    .map(s => (s || '').trim())
    .filter(Boolean)
  return [...parts, ...tail].join('，')
}

/** 骰一个种子。取值域和后端 comfyui._MAX_SEED 同源——都是 ComfyUI 前端那行
 *  `Math.min(1125899906842624, max)` 夹出来的 2^50。 */
function randomSeed(): number {
  return Math.floor(Math.random() * 2 ** 50)
}

export default function NpcAvatarField({ npc, onChanged, genre, imageConfig, place }: {
  npc: RpgNpc
  onChanged: (npc: RpgNpc) => void
  /** 模组的题材，拼进提示词 */
  genre: string
  /** 模组的出图设置：这个角色的默认值和基线。他自己那份覆写在弹窗里调 */
  imageConfig: RpgImageConfig
  /** 这个人常驻地点在地点表里那一条，拿它的描述当背景。没填地点就是 undefined */
  place?: RpgLocation
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [viewing, setViewing] = useState(false)

  const run = async (fn: () => Promise<RpgNpc>, fail: string) => {
    setBusy(true)
    try {
      onChanged(await fn())
    } catch (e: any) {
      // ComfyUI 的报错会指明哪个节点哪个字段，值得多留一会儿
      toast.error(e?.response?.data?.detail || fail, { duration: 8000 })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-start gap-3">
      <button
        onClick={() => (npc.avatar_url ? setViewing(true) : fileRef.current?.click())}
        disabled={busy}
        className="w-16 h-16 rounded-xl shrink-0 flex items-center justify-center overflow-hidden
          ring-1 ring-primary/25 bg-primary/10 text-primary hover:ring-primary/60 transition-colors"
        title={npc.avatar_url ? '看大图' : '上传立绘'}
      >
        {busy
          ? <Loader2 className="w-5 h-5 animate-spin" />
          : npc.avatar_url
            ? <img src={npc.avatar_url} alt={npc.name} className="w-full h-full object-cover" />
            : <ImagePlus className="w-6 h-6" />}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={e => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (file) run(() => rpgApi.npcs.uploadAvatar(npc.id, file), '上传立绘失败')
        }}
      />

      <div className="flex-1 min-w-0">
        <label className="text-xs font-medium mb-1.5 block">立绘（选填）</label>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setAsking(true)}
            disabled={busy}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border
              border-primary/40 text-primary hover:bg-primary/10 disabled:opacity-50"
          >
            <Sparkles className="w-3.5 h-3.5" /> 生成立绘
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border
              hover:bg-muted disabled:opacity-50"
          >
            <ImagePlus className="w-3.5 h-3.5" /> {npc.avatar_url ? '换一张' : '上传'}
          </button>
          {npc.avatar_url && (
            <button
              onClick={() => run(() => rpgApi.npcs.deleteAvatar(npc.id), '移除立绘失败')}
              disabled={busy}
              className="text-xs text-muted-foreground hover:text-red-400 disabled:opacity-50"
            >
              移除
            </button>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          生成要连本机 ComfyUI，地址在设置页。冷启动第一张慢（要加载模型），之后二十秒上下。
        </p>
        {npc.avatar_seed > 0 && (
          <p className="text-[11px] text-muted-foreground mt-1">
            当前立绘种子 <span className="font-mono">{npc.avatar_seed}</span>
            ，填回去能保住同一张脸。
          </p>
        )}
      </div>

      {asking && (
        <GenerateDialog
          npc={npc}
          genre={genre}
          moduleConfig={imageConfig}
          place={place}
          onClose={() => setAsking(false)}
          onSubmit={async (prompt, seed, width, height) => {
            setAsking(false)
            await run(
              () => rpgApi.npcs.generateAvatar(npc.id, prompt, seed, width, height),
              '生成立绘失败',
            )
          }}
          onNpcChanged={onChanged}
        />
      )}
      {viewing && npc.avatar_url && (
        <ImageLightbox url={npc.avatar_url} alt={npc.name} onClose={() => setViewing(false)} />
      )}
    </div>
  )
}

/**
 * 提示词过目一眼再发。预填是从外貌字段加合并后的出图设置拼的，多半还要手改。
 *
 * 这个弹窗**自己拿着**这个角色的那份出图设置（稀疏覆写），因为只有它知道用户
 * 什么时候算「调完了」——是关窗或者点生成那一下。父组件那份 `moduleConfig`
 * 是模组的，只读，当基线用。
 */
function GenerateDialog({
  npc, genre, moduleConfig, place, onClose, onSubmit, onNpcChanged,
}: {
  npc: RpgNpc
  genre: string
  /** 模组那份设置，「跟随模组」时的取值来源 */
  moduleConfig: RpgImageConfig
  place?: RpgLocation
  onClose: () => void
  onSubmit: (prompt: string, seed: number | undefined, width: number, height: number) => void
  /** 设置存库之后把新的这个人交回页面，让列表里的值跟着刷新 */
  onNpcChanged: (npc: RpgNpc) => void
}) {
  const [npcCfg, setNpcCfg] = useState<RpgImageConfig>(npc.image_config || {})
  // buildPrompt 从父组件挪进来了：设置一改这句话就得跟着重算，留在外面
  // 就得把合并结果再往上抬一层
  const merged = mergeImageConfig(moduleConfig, npcCfg)
  const auto = buildPrompt(npc, genre, merged, place)
  // 光辉这类工作流走 CLIP-L 只认英文 tag，中文散文喂进去基本等于噪声。缺省
  // （undefined）当中文，只有显式选了 sd_tags 才转 tag，老模组不受影响
  const isTags = merged.prompt_form === 'sd_tags'
  const frame = frameOf(merged.frame)

  const [text, setText] = useState(auto)
  const [touched, setTouched] = useState(false)
  // 没手动改过就跟着下面的设置走，改过就再也不覆盖。
  // 一边打字一边被自动重算的字冲掉是最惹人烦的交互——用户刚删掉那段地点描述，
  // 手还没离开键盘就被塞回来了。宁可多摆一个按钮让他主动点
  useEffect(() => {
    if (!touched) setText(auto)
  }, [auto, touched])

  // ── sd_tags 专用：中文源文（上面那句 auto）→ 英文 tag ──
  // **不自动转**：转换要调后端跑两趟 LLM，而「成人内容」和「带不带角色名」这两个
  // 开关会直接改变转出来的 tag。先让用户勾好，再点一下「转换」——否则一打开就先
  // 转一次，用户勾完还得再点「重新转换」白烧一轮 token
  const [tagText, setTagText] = useState('')
  const [tagTouched, setTagTouched] = useState(false)
  const [dropped, setDropped] = useState<string[]>([])
  const [converting, setConverting] = useState(false)
  // 记下上次转换时的源文 + 两个开关，任一变了就算「过期」。null = 还没转过
  const [convertedKey, setConvertedKey] = useState<string | null>(null)
  // 成人内容默认**开**：这是作者自己的出图工具，成人向模组是常态，默认关上等于
  // 每次都要手动点一遍。转不转由这一勾决定，不勾就是照常规转
  const [nsfw, setNsfw] = useState(true)
  // 是否把角色名也转成 Danbooru 角色 tag（做同人时用）。默认关：原创角色带名字
  // 反而会让底模往某个已知角色的脸上靠
  const [includeCharName, setIncludeCharName] = useState(false)
  const convertKey = `${nsfw ? 1 : 0}${includeCharName ? 1 : 0}|${auto}`
  const tagsStale = convertedKey !== null && convertedKey !== convertKey
  const neverConverted = convertedKey === null

  const runConvert = async () => {
    setConverting(true)
    try {
      const r = await rpgApi.npcs.promptAsTags(npc.id, auto, nsfw, includeCharName)
      setTagText(r.tags.join(', '))
      setDropped(r.dropped)
      setConvertedKey(convertKey)
      setTagTouched(false)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || '转 tag 失败', { duration: 8000 })
    } finally {
      setConverting(false)
    }
  }

  // 种子输入框**故意初始留空**：预填上次那个值等于默认每次同种子，连点两次
  // 「生成」会得到一模一样的图，那正是当初 ComfyUI 命中缓存那个坑的翻版。
  // 要复现得显式点一下「上次」
  const [seedText, setSeedText] = useState('')

  const seed = seedText.trim() === '' ? undefined : Math.floor(Number(seedText))
  // number 输入框拦不住手打的超范围值，上限跟 ComfyUI 一致（2^50-1）
  const seedBad = seed !== undefined
    && (!Number.isFinite(seed) || seed < 0 || seed > 2 ** 50 - 1)

  const lastSeed = npc.avatar_seed
  const changed = JSON.stringify(npcCfg) !== JSON.stringify(npc.image_config || {})

  /** 把这个人那份设置写进库。只在关窗和点生成这两个时刻调，**不做逐键防抖**：
   *  防抖的延时和「生成前必须先落库」这个时机要求是打架的（抖还没停图就发出去
   *  了），而且拖一下滑块发十几个请求也太吵。 */
  const flushCfg = async () => {
    if (!changed) return
    try {
      onNpcChanged(await rpgApi.npcs.update(npc.id, { image_config: npcCfg }))
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || '出图设置没存上', { duration: 8000 })
    }
  }

  // 关窗也要补一次：只调设置不生成的话，不写库这一通就白调了
  const close = async () => {
    await flushCfg()
    onClose()
  }

  // 真正发出去的提示词：tag 形态发 tag 框里的英文，中文形态发上面那句
  const finalPrompt = (isTags ? tagText : text).trim()

  const submit = async () => {
    // **先落库再发生成请求**：后端出图时工作流和 LoRA 是从库里现读的，
    // 顺序反了出的就是旧设置那张图，而用户会以为自己刚才改的没生效
    await flushCfg()
    // 尺寸由画幅档决定，回表查出来传进请求体——工作流里得先有 %WIDTH%/%HEIGHT%
    // 占位符，否则后端填不进去、还是出工作流写死的尺寸
    onSubmit(finalPrompt, seed, frame.width, frame.height)
  }

  const overridden = Object.keys(npcCfg).length

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={close}
    >
      <div
        className="w-full max-w-2xl rounded-2xl border border-primary/25 bg-card shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="border-b px-6 py-4 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <p className="font-semibold">生成立绘</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {isTags
                ? '光辉工作流：中文源文转成英文 tag 再发，tag 框可以随便改。'
                : '从外貌那几栏拼的，改完再发。中文直接写就行。'}
            </p>
          </div>
          <button onClick={close} className="p-1 rounded hover:bg-muted shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">
          {isTags ? (
            <>
              {/* 源文只读：tag 是从它转来的，改源文要点「重新转换」才生效。
                  想直接改词就改下面的 tag 框 */}
              <label className="text-xs font-medium mb-1.5 block">中文源文（只读）</label>
              <p className={`${INPUT} min-h-[4rem] whitespace-pre-wrap text-muted-foreground
                bg-muted/40 cursor-default`}>
                {auto}
              </p>

              {/* 选项在**转换之前**：这两勾会直接改变转出来的 tag，所以先定好再点
                  「转换」，转完想改再点「重新转换」 */}
              <div className="mt-3 space-y-1.5">
                <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-primary"
                    checked={nsfw}
                    onChange={e => setNsfw(e.target.checked)}
                  />
                  成人内容照实转（默认开）
                </label>
                <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-primary"
                    checked={includeCharName}
                    onChange={e => setIncludeCharName(e.target.checked)}
                  />
                  把角色名「{npc.name}」转成角色 tag（做同人时勾，默认关）
                </label>
              </div>

              <div className="flex items-center justify-between mt-4 mb-1.5">
                <label className="text-xs font-medium">Danbooru tag（可改）</label>
                <button
                  onClick={runConvert}
                  disabled={converting}
                  className="flex items-center gap-1 text-xs text-primary hover:underline disabled:opacity-50"
                >
                  {converting
                    ? <Loader2 className="w-3 h-3 animate-spin" />
                    : <RefreshCw className="w-3 h-3" />}
                  {neverConverted ? '转换' : '重新转换'}
                </button>
              </div>
              <textarea
                value={tagText}
                onChange={e => { setTagText(e.target.value); setTagTouched(true) }}
                placeholder={converting
                  ? '转换中…'
                  : (neverConverted ? '勾好上面的选项，点「转换」' : '1girl, silver_hair, ...')}
                className={`${INPUT} resize-y min-h-[8rem] font-mono text-xs`}
                autoFocus
              />
              {tagsStale && !tagTouched && (
                <p className="text-xs text-amber-500 mt-1.5">
                  源文或上面的开关变了，这些 tag 还是旧的。点「重新转换」刷新。
                </p>
              )}
              {dropped.length > 0 && (
                <p className="text-xs text-muted-foreground mt-1.5">
                  这几个词词表里没有、没转成功，已从 tag 里去掉：
                  <span className="text-amber-500">{dropped.join('、')}</span>。
                  想要就手动改成相近的真 tag。
                </p>
              )}
            </>
          ) : (
            <>
          <textarea
            value={text}
            onChange={e => { setText(e.target.value); setTouched(true) }}
            placeholder="银发及腰，左眼下一颗泪痣，洗旧的藏青色制服，站姿全身像"
            className={`${INPUT} resize-y min-h-[8rem]`}
            autoFocus
          />
          {touched && (
            <p className="text-xs text-muted-foreground mt-1.5">
              你手改过这一句，下面的设置不再自动改写它了。
              <button
                onClick={() => { setText(auto); setTouched(false) }}
                className="ml-1 text-primary hover:underline"
              >
                按设置重拼一遍
              </button>
            </p>
          )}
            </>
          )}

          <label className="text-xs font-medium mt-4 mb-1.5 block">随机种子（选填）</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={2 ** 50 - 1}
              value={seedText}
              onChange={e => setSeedText(e.target.value)}
              placeholder="留空 = 每次随机"
              className={`${INPUT} flex-1 font-mono`}
            />
            <button
              onClick={() => setSeedText(String(randomSeed()))}
              title="骰一个"
              className="p-2 rounded-lg border hover:bg-muted shrink-0"
            >
              <Dices className="w-4 h-4" />
            </button>
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">
            {seedBad
              ? <span className="text-red-400">种子要在 0 ~ 1125899906842623 之间。</span>
              : '同一句提示词配同一个种子，出的是同一张图。想换个姿势保住同一张脸，就把种子填上。'}
            {lastSeed > 0 && (
              <>
                {' '}
                <button
                  onClick={() => setSeedText(String(lastSeed))}
                  className="text-primary hover:underline"
                >
                  上次：{lastSeed}
                </button>
              </>
            )}
          </p>

          {/* 折叠着的：多数时候模组那份就够用，摊开会把提示词框挤出视野。
              用原生 details 是因为这里不引组件库 */}
          <details className="mt-4 rounded-lg border">
            <summary className="px-3 py-2 text-xs font-medium cursor-pointer select-none
              flex items-center justify-between gap-2 hover:bg-muted/50 rounded-lg">
              <span>只给这个角色的出图设置（不动就跟着模组）</span>
              {overridden > 0 && (
                <span className="shrink-0 text-[10px] text-primary">已改 {overridden} 项</span>
              )}
            </summary>
            <div className="px-3 pt-3 pb-3 border-t">
              <ImageSettingsFields
                cfg={npcCfg}
                onChange={setNpcCfg}
                genre={genre}
                inherit={moduleConfig}
              />
            </div>
          </details>
        </div>
        <div className="border-t px-6 py-3 flex justify-end gap-2">
          <button onClick={close} className="text-sm px-4 py-2 rounded-lg hover:bg-muted">
            {changed ? '存下设置，先不出图' : '取消'}
          </button>
          <button
            onClick={submit}
            disabled={!finalPrompt || seedBad || converting}
            className="text-sm px-4 py-2 rounded-lg bg-primary text-primary-foreground
              hover:opacity-90 disabled:opacity-50"
          >
            开始生成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
