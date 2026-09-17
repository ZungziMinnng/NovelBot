import { Loader2, RotateCcw } from 'lucide-react'
import type { RpgNpc, RpgSettlement } from '@/api/client'

const LABELS: Record<string, string> = {
  scene: '地点与在场人物', stats: '数值', inventory: '背包',
  characters: '人物', flags: '处境', memory: '长期记忆',
}
const STATUS: Record<string, string> = {
  pending: '等待结算', running: '正在结算', done: '结算完成',
  partial: '部分变化尚未确认', failed: '结算失败，剧情已保留', stale: '正文已修改，需要重新结算',
  updated: '已更新', unchanged: '无变化', needs_review: '待核对',
}

export default function SettlementReport({ report, latest, busy, disabled, npcs, onRetry }: {
  report: RpgSettlement
  latest: boolean
  busy: boolean
  disabled: boolean
  npcs: RpgNpc[]
  onRetry: () => void
}) {
  const incomplete = report.status !== 'done'
  return (
    <div className={`rounded-xl border px-3 py-2 text-xs space-y-2 ${incomplete ? 'border-amber-500/30 bg-amber-500/5' : 'border-border/60 text-muted-foreground'}`}>
      <div className="flex items-center justify-between gap-3">
        <span>{busy ? '正在重新核对本回合…' : STATUS[report.status] || report.status}</span>
        {incomplete && report.retryable && latest && (
          <button onClick={onRetry} disabled={disabled || busy} className="flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 hover:bg-muted disabled:opacity-50">
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
            仅重新结算
          </button>
        )}
      </div>
      {!!report.changes?.length && <p>{report.changes.join('；')}</p>}
      {incomplete && !latest && <p>后面已有新回合，需要从对应玩家消息回滚重玩。</p>}
      {!!report.warnings?.length && <p className="text-amber-600 dark:text-amber-400">{report.warnings.join('；')}</p>}
      <details>
        <summary className="cursor-pointer">核对结果与原文依据</summary>
        <div className="space-y-2 pt-2">
          {Object.entries(report.domains || {}).map(([domain, result]) => (
            <div key={domain}>
              {LABELS[domain] || domain}：{STATUS[result.status] || result.status}
              {!!result.warnings?.length && <p className="text-amber-600 dark:text-amber-400">{result.warnings.join('；')}</p>}
            </div>
          ))}
          {(report.facts || []).map((fact, index) => (
            <div key={`${index}-${fact.kind}`} className="rounded-lg bg-muted/50 p-2 space-y-1">
              <p>{fact.summary}</p>
              <blockquote className="border-l-2 pl-2 whitespace-pre-wrap">{fact.quote}</blockquote>
              <p>{fact.visibility === 'public' ? '已公开' : `知情：你${(fact.witnesses || []).map(identity => npcs.find(npc => npc.id === identity)?.name).filter(Boolean).map(name => `、${name}`).join('')}`}</p>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}
