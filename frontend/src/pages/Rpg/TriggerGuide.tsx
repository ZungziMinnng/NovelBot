import type { ReactNode } from 'react'
import { UserPlus, DoorOpen, EyeOff } from 'lucide-react'

/**
 * 「条件触发指南」抽屉的正文。
 *
 * 只讲两套配方：让人出场、解锁秘境。这两件事在引擎里是同一个套路——先用一个
 * 玩家看不见的计数器记下「那件事发生过」，再让世界书或地点去查这个计数。
 * 这套拼法是之前为了一个「条件到了才登场」的模组摸了半天摸出来的，界面上却
 * 一个字都没有，所以把摸出来的东西写在这儿。
 *
 * 例子统一用「触碰古镜 → 古镜空间」这条线，别换回项目里那个敏感题材的旧例子。
 *
 * 文案里出现的字段名（数值门槛 / 常驻 / 玩家数值变化 / 生效条件 / 进入条件）
 * 全是各面板上已经印着的原话，别在这儿另造名词——对不上就等于没写。
 */

/** 界面上某个要填的框。用原话，别改 */
function Field({ children }: { children: ReactNode }) {
  return (
    <code className="px-1.5 py-0.5 rounded bg-muted text-[12px] text-foreground/90">{children}</code>
  )
}

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <span className="shrink-0 mt-0.5 w-4 h-4 rounded-full bg-primary/10 text-primary text-[10px] font-medium flex items-center justify-center">
        {n}
      </span>
      <div className="flex-1 min-w-0 space-y-1.5">{children}</div>
    </li>
  )
}

/** 步骤下面那行「为什么这么填」 */
function Note({ children }: { children: ReactNode }) {
  return (
    <p className="text-[12px] text-muted-foreground leading-relaxed border-l-2 border-border pl-2">
      {children}
    </p>
  )
}

function Recipe({
  icon, title, sub, children,
}: {
  icon: ReactNode; title: string; sub: string; children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-border/70 p-3.5 space-y-3">
      <div>
        <div className="text-sm font-medium flex items-center gap-1.5">
          {icon} {title}
        </div>
        <div className="text-[12px] text-muted-foreground mt-0.5">{sub}</div>
      </div>
      <ol className="space-y-3">{children}</ol>
    </section>
  )
}

export default function TriggerGuide() {
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground leading-relaxed">
        想让谁在什么条件下登场、想藏一个地点等条件到了才开，引擎一律不看剧情文字，
        <span className="text-foreground">只看数值</span>。所以配方永远是同一招：
        <span className="text-foreground">用一个玩家看不见的计数器，记下「那件事发生过」，再让世界书或地点去查这个计数。</span>
      </p>

      <Recipe
        icon={<UserPlus className="w-4 h-4 text-primary" />}
        title="配方一 · 让人出场"
        sub="例：触碰古镜之后，镜中人才现身"
      >
        <Step n={1}>
          <div className="leading-relaxed">
            <Field>数值</Field> 面板 → 加一条玩家数值，名字比如 <Field>触碰古镜次数</Field>，
            显示方式选 <Field>隐藏</Field>。
          </div>
          <Note>
            隐藏 = 后台计数器。玩家界面上看不见，但能拿来触发世界书词条。
          </Note>
        </Step>

        <Step n={2}>
          <div className="leading-relaxed">
            <Field>动作</Field> 面板 → 加一个按钮（比如「触碰古镜」），
            <Field>玩家数值变化</Field> 里写 <Field>触碰古镜次数 +1</Field>。
          </div>
          <Note>
            动作是引擎直接结算的，点了就一定加上，不靠 AI 发挥。反过来，动作只能改数值——
            它那一栏里没有「写剧情标记」这个选项。
          </Note>
        </Step>

        <Step n={3}>
          <div className="leading-relaxed">
            <Field>世界书</Field> 面板 → 加一条词条，勾上 <Field>常驻</Field>，
            正文写清「发生什么、谁出现」。然后在 <Field>生效条件</Field> 里加一条
            <Field>数值门槛</Field>：<Field>触碰古镜次数 &gt;= 1</Field>。
          </div>
          <Note>
            常驻 = 不看关键词，每轮都注入。真正决定它这轮出不出现的是底下的生效条件。
          </Note>
        </Step>

        <Step n={4}>
          <div className="leading-relaxed">
            <Field>角色</Field> 面板 → 把这个人建好。到这里就配完了。
          </div>
          <Note>
            角色卡里<span className="text-foreground">没有「出场条件」这个字段</span>——
            TA 是被第 3 步那条词条写进场面里的，不是靠角色卡上的开关。
          </Note>
        </Step>
      </Recipe>

      <Recipe
        icon={<DoorOpen className="w-4 h-4 text-primary" />}
        title="配方二 · 解锁秘境"
        sub="例：条件到了，古镜空间才进得去"
      >
        <Step n={1}>
          <div className="leading-relaxed">
            <Field>地点</Field> 面板 → 建好地点（比如「古镜空间」），
            在 <Field>进入条件</Field> 里放
            <span className="text-foreground">和配方一同一个</span>数值门槛
            （<Field>触碰古镜次数 &gt;= 1</Field>）。
          </div>
          <Note>
            条件没满足时这个地点在界面上就是进不去的，不用另外做开关。
          </Note>
        </Step>

        <Step n={2}>
          <div className="leading-relaxed">
            <Field>世界书</Field> 面板 → 再配一条词条，写「进去之后看见什么」。
          </div>
          <Note>
            地点负责「能不能进」，词条负责「进去之后发生什么」，是两件事，得各配一份。
            只配了地点，人会走进一个空房间。
          </Note>
        </Step>
      </Recipe>

      <section className="rounded-xl border border-border/70 p-3.5 space-y-2">
        <div className="text-sm font-medium flex items-center gap-1.5">
          <EyeOff className="w-4 h-4 text-primary" /> 为什么非得用隐藏数值
        </div>
        <ul className="space-y-1.5 text-[12px] text-muted-foreground leading-relaxed list-disc pl-4">
          <li>
            按钮点下去只能改数值，所以计数器是动作能落下的唯一痕迹；
          </li>
          <li>
            门槛判的是数值本身，不是 AI 的说法，所以点三次就是三次，读档重来也认；
          </li>
          <li>
            换成「剧情标记」也能做条件，但标记要等 AI 结算时才写得进去，
            按钮点完不一定当场生效。
          </li>
        </ul>
      </section>
    </div>
  )
}
