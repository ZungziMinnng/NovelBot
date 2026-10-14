import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Check, Eye, Lock, Plus, X } from 'lucide-react'
import { rpgApi } from '@/api/client'
import type { RpgNpc, RpgSecret, RpgSecretProposal, RpgSession } from '@/api/client'
import { PANEL } from '../rpgUi'

const STANCE_TEXT: Record<string, string> = {
  knows: '得知了', suspects: '起疑了', misled: '被骗了',
}

function describe(p: RpgSecretProposal): string {
  if (p.kind === 'retire') return `已公开：${p.content}`
  if (p.kind === 'new') {
    const known = p.known_names?.length ? `，${p.known_names.join('、')}知情` : ''
    return `新秘密（${p.owner_name || '某人'}的）：${p.content}${known}`
  }
  const tail = p.stance === 'misled' && p.belief ? `，信的是「${p.belief}」` : ''
  return `${p.npc_name || '某人'}${STANCE_TEXT[p.stance || 'knows']}：${p.content}${tail}`
}

/** 知情账：一条一件秘密，勾出谁知道。写正文的模型据此让不知情的人装作不知道。
 *  这里只改账，不改剧情——某人"知道了"要玩家自己点，剧情里发生了什么不会自动记进来。 */
export default function SecretPanel({ sess, npcs }: { sess: RpgSession; npcs: RpgNpc[] }) {
  const qc = useQueryClient()
  const secrets = sess.secrets || []
  const [adding, setAdding] = useState(false)
  const [content, setContent] = useState('')
  const [owner, setOwner] = useState(0)
  const [knownBy, setKnownBy] = useState<number[]>([])
  const [busy, setBusy] = useState(false)

  const proposals = sess.secret_proposals || []
  const nameOf = (id: number) => npcs.find(n => n.id === id)?.name || '某人'
  const save = (next: RpgSession) => qc.setQueryData(['rpg-session', sess.id], next)
  const run = async (job: () => Promise<RpgSession>, fail: string) => {
    if (busy) return
    setBusy(true)
    try { save(await job()) } catch { toast.error(fail) } finally { setBusy(false) }
  }

  const toggle = (id: number) =>
    setKnownBy(cur => (cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]))

  const submit = async () => {
    if (!content.trim()) return
    await run(async () => {
      const next = await rpgApi.sessions.addSecret(sess.id, {
        content: content.trim(), owner, known_by: knownBy.filter(id => id !== owner),
        player_knows: false,
      })
      setContent(''); setKnownBy([]); setOwner(0); setAdding(false)
      return next
    }, '没能登记（内容为空，或秘密已经满了）')
  }

  const toggleKnown = (s: RpgSecret, id: number) => {
    const has = s.known_by.includes(id)
    return run(
      () => rpgApi.sessions.patchSecret(sess.id, s.id, {
        known_by: has ? s.known_by.filter(x => x !== id) : [...s.known_by, id],
      }),
      '没能改',
    )
  }

  return (
    <div className="pt-2 space-y-2">
      <div className="flex items-center justify-between px-1">
        <p className="text-[11px] text-muted-foreground flex items-center gap-1">
          <Lock className="w-3 h-3" />秘密 {secrets.length} 条
        </p>
        <button
          onClick={() => setAdding(v => !v)}
          className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-0.5"
        >
          <Plus className="w-3 h-3" />登记
        </button>
      </div>

      {proposals.length > 0 && (
        <div className={`${PANEL} p-2.5 space-y-2 border-primary/40`}>
          <p className="text-[11px] text-muted-foreground">剧情里好像发生了这些，认不认？</p>
          {proposals.map(p => (
            <div key={p.id} className="space-y-1">
              <p className="text-xs leading-relaxed">{describe(p)}</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">「{p.quote}」</p>
              <div className="flex gap-2 text-[11px]">
                <button
                  onClick={() => run(() => rpgApi.sessions.resolveSecrets(sess.id, [{ id: p.id, accept: true }]), '没能记')}
                  className="flex items-center gap-0.5 text-foreground hover:underline"
                ><Check className="w-3 h-3" />记下</button>
                <button
                  onClick={() => run(() => rpgApi.sessions.resolveSecrets(sess.id, [{ id: p.id, accept: false }]), '没能忽略')}
                  className="flex items-center gap-0.5 text-muted-foreground hover:text-foreground"
                ><X className="w-3 h-3" />不算</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {adding && (
        <div className={`${PANEL} p-2.5 space-y-2`}>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            maxLength={120}
            rows={2}
            placeholder="一句话写清楚这件秘密"
            className="w-full text-xs bg-transparent border rounded-md p-1.5 resize-none"
          />
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            属于
            <select
              value={owner}
              onChange={e => setOwner(Number(e.target.value))}
              className="bg-transparent border rounded px-1 py-0.5 text-foreground"
            >
              <option value={0}>玩家（你）</option>
              {npcs.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </label>
          <div className="text-[11px] text-muted-foreground">
            谁已经知道（不选 = 没人知道）：
            <div className="flex flex-wrap gap-1 mt-1">
              {npcs.filter(n => n.id !== owner).map(n => (
                <button
                  key={n.id}
                  onClick={() => toggle(n.id)}
                  className={`px-1.5 py-0.5 rounded border ${knownBy.includes(n.id)
                    ? 'bg-primary/15 border-primary/40 text-foreground' : 'border-border/60'}`}
                >
                  {n.name}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={submit}
            disabled={busy || !content.trim()}
            className="w-full text-xs py-1 rounded-md bg-primary/15 hover:bg-primary/25 disabled:opacity-50"
          >
            记下来
          </button>
        </div>
      )}

      {secrets.length === 0 && !adding && (
        <p className="text-xs text-muted-foreground px-1 leading-relaxed">
          还没有登记秘密。登记后，不知情的人在剧情里会被要求装作不知道。
        </p>
      )}

      {secrets.map(s => (
        <div key={s.id} className={`${PANEL} p-2.5 space-y-1.5`}>
          <div className="flex items-start gap-1.5">
            <p className="text-xs leading-relaxed flex-1">{s.content}</p>
            <button
              onClick={() => run(() => rpgApi.sessions.deleteSecret(sess.id, s.id), '没能划掉')}
              title="划掉：已经公开了，或者记错了"
              className="text-muted-foreground hover:text-foreground shrink-0"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            {s.owner === 0 ? '玩家的秘密' : `${s.names?.[String(s.owner)] || nameOf(s.owner)}的秘密`}
            {s.owner !== 0 && !s.player_knows && '（玩家还不知道）'}
          </p>
          {(s.suspects?.length || Object.keys(s.misled || {}).length) ? (
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {s.suspects?.length ? `起疑：${s.suspects.map(i => s.names?.[String(i)] || nameOf(i)).join('、')}　` : ''}
              {Object.entries(s.misled || {}).map(([k, v]) => `${s.names?.[k] || nameOf(Number(k))}被骗，信的是「${v}」`).join('；')}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-1 items-center text-[11px]">
            <span className="text-muted-foreground">知情：</span>
            {npcs.filter(n => n.id !== s.owner).map(n => (
              <button
                key={n.id}
                onClick={() => toggleKnown(s, n.id)}
                className={`px-1.5 py-0.5 rounded border ${s.known_by.includes(n.id)
                  ? 'bg-primary/15 border-primary/40' : 'border-border/60 text-muted-foreground'}`}
              >
                {n.name}
              </button>
            ))}
          </div>
          {s.owner !== 0 && !s.player_knows && (
            <button
              onClick={() => run(
                () => rpgApi.sessions.patchSecret(sess.id, s.id, { player_knows: true }), '没能改',
              )}
              className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <Eye className="w-3 h-3" />标为玩家已查明
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
