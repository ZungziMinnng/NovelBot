import { useEffect, useState } from 'react'
import type { RpgBand, RpgOutcome, RpgRoll } from '@/api/client'
import { playSfx } from './useSfx'

/** 数字翻滚多久。这段等待是故意留的：判定那次调用本来就要花一两秒，
 *  「先看结果再看文字」是玩家期待的节奏，正好把延迟变成正反馈 */
const ROLL_MS = 1100

// 成败是语义色（绿=成功红=失败），不能跟着 --primary 走。
// 但深浅两种底都得看得清，所以每条都写成双基底
const OUTCOME_STYLE: Record<RpgOutcome, { label: string; chip: string; die: string }> = {
  crit_success: {
    label: '大成功',
    chip: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-emerald-500/40',
    die: 'bg-emerald-500/20 text-emerald-800 dark:text-emerald-200 ring-emerald-500/60',
  },
  success: {
    label: '成功',
    chip: 'bg-teal-500/15 text-teal-700 dark:text-teal-300 ring-teal-500/40',
    die: 'bg-teal-500/15 text-teal-800 dark:text-teal-200 ring-teal-500/50',
  },
  narrow: {
    label: '险胜',
    chip: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-amber-500/40',
    die: 'bg-amber-500/15 text-amber-800 dark:text-amber-200 ring-amber-500/50',
  },
  fail: {
    label: '失败',
    chip: 'bg-rose-500/15 text-rose-700 dark:text-rose-300 ring-rose-500/40',
    die: 'bg-rose-500/15 text-rose-800 dark:text-rose-200 ring-rose-500/50',
  },
  crit_fail: {
    label: '大失败',
    chip: 'bg-red-500/20 text-red-700 dark:text-red-300 ring-red-500/50',
    die: 'bg-red-500/20 text-red-800 dark:text-red-200 ring-red-500/60',
  },
}

const BAND_LABEL: Record<RpgBand, string> = {
  trivial: '轻易', easy: '简单', medium: '普通', hard: '困难', extreme: '极难',
}

/**
 * 一次判定的结果条。显示的是成功率而不是「D20+2 对抗 16」——
 * 前者不用玩家懂加值公式也看得懂自己有多大机会。
 *
 * dice = 0 表示模组关了随机，结果纯看数值，那就不画掷点。
 * animate 只在这一轮刚判出来时为真，翻历史不该每条都再抖一遍。
 */
export default function DiceRoll({ roll, animate = false }: { roll: RpgRoll; animate?: boolean }) {
  const rate = roll.rate ?? 0
  const dice = roll.dice ?? 0
  const random = dice > 0
  const spin = animate && random

  const [face, setFace] = useState(spin ? 1 : dice)
  const [rolling, setRolling] = useState(spin)

  useEffect(() => {
    if (!spin) {
      setRolling(false)
      setFace(dice)
      return
    }
    setRolling(true)
    playSfx('dice')
    const flicker = setInterval(() => setFace(1 + Math.floor(Math.random() * 100)), 70)
    const stop = setTimeout(() => {
      clearInterval(flicker)
      setFace(dice)
      setRolling(false)
    }, ROLL_MS)
    return () => { clearInterval(flicker); clearTimeout(stop) }
  }, [spin, dice])

  if (!roll.need_check || !roll.outcome) return null

  const style = OUTCOME_STYLE[roll.outcome]

  return (
    <div className="flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/[0.06] px-3 py-2">
      <div
        className={`w-11 h-10 rounded-lg ring-1 flex items-center justify-center font-bold text-base shrink-0
          transition-transform duration-200 ${style.die} ${rolling ? 'scale-110 -rotate-6' : 'scale-100 rotate-0'}`}
        title={random ? '掷点 1~100，不超过成功率就算过' : '这个模组关了随机，结果只看数值'}
      >
        {random ? face : `${rate}%`}
      </div>
      <div className="min-w-0 flex-1 text-xs">
        <p className="flex items-center gap-1.5 flex-wrap">
          <span className="font-medium text-primary">{roll.attr}</span>
          <span className="text-muted-foreground">
            {BAND_LABEL[roll.band]} · 成功率 {rate}%
          </span>
          {rolling ? (
            <span className="text-muted-foreground animate-pulse">判定中…</span>
          ) : (
            <>
              {random && <span className="text-muted-foreground">掷出 {face}</span>}
              <span className={`px-1.5 py-0.5 rounded-full ring-1 font-medium ${style.chip}`}>
                {style.label}
              </span>
            </>
          )}
        </p>
        {roll.intent && (
          <p className="text-[11px] text-muted-foreground/70 truncate mt-0.5">{roll.intent}</p>
        )}
      </div>
    </div>
  )
}
