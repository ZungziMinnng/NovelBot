import { useState } from 'react'
import { X, Download, ShieldAlert, Loader2, FileText, FileArchive } from 'lucide-react'
import toast from 'react-hot-toast'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { novelsApi, submissionApi, type Novel, type SensitiveScanResult } from '@/api/client'

interface Props {
  novel: Novel
  onClose: () => void
}

type Tab = 'meta' | 'export' | 'check'

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'meta', label: '书名简介' },
  { key: 'export', label: '导出稿件' },
  { key: 'check', label: '过审预检' },
]

export default function SubmissionModal({ novel, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('meta')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-background rounded-xl shadow-xl max-h-[85vh] overflow-y-auto w-[640px] mx-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-background border-b px-5 py-3 flex items-center gap-3 z-10 rounded-t-xl">
          <h2 className="font-bold text-base flex-1">投稿准备</h2>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 pt-4 flex gap-1 border-b">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
                tab === t.key ? 'border-primary text-primary font-medium' : 'border-transparent hover:bg-muted'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="p-5">
          {tab === 'meta' && <MetaTab novel={novel} />}
          {tab === 'export' && <ExportTab novelId={novel.id} />}
          {tab === 'check' && <CheckTab novelId={novel.id} />}
        </div>
      </div>
    </div>
  )
}

// ── 书名 / 简介 / 标签 ───────────────────────────────────────────────────────

function MetaTab({ novel }: { novel: Novel }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState(novel.title)
  const [blurb, setBlurb] = useState(novel.blurb || '')
  const [tagText, setTagText] = useState((novel.submission_tags || []).join(' '))

  const save = useMutation({
    mutationFn: () =>
      novelsApi.update(novel.id, {
        title: title.trim(),
        blurb,
        submission_tags: tagText.split(/[\s,，、]+/).filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['novel', novel.id] })
      qc.invalidateQueries({ queryKey: ['novels'] })
      toast.success('已保存')
    },
    onError: () => toast.error('保存失败'),
  })

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        番茄、起点开书时书名、简介、标签都是必填项。填在这里，导出的稿件开头会带上。
      </p>
      <div>
        <label className="text-sm font-medium">书名</label>
        <input
          value={title}
          onChange={e => setTitle(e.target.value)}
          className="mt-1 w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <div>
        <label className="text-sm font-medium">作品简介</label>
        <span className="text-xs text-muted-foreground ml-2">{blurb.length} 字，平台一般限 300 字内</span>
        <textarea
          value={blurb}
          onChange={e => setBlurb(e.target.value)}
          rows={7}
          placeholder="开头两句要抓人：主角处境 + 核心冲突 + 金手指/爽点，别写世界观科普。"
          className="mt-1 w-full text-sm border rounded-lg px-3 py-2 bg-background resize-y focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <div>
        <label className="text-sm font-medium">平台标签</label>
        <input
          value={tagText}
          onChange={e => setTagText(e.target.value)}
          placeholder="空格或逗号分隔，例：重生 系统 都市 逆袭"
          className="mt-1 w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="flex items-center gap-2 text-sm px-3 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
      >
        {save.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 保存
      </button>
    </div>
  )
}

// ── 导出 ─────────────────────────────────────────────────────────────────────

function ExportTab({ novelId }: { novelId: number }) {
  const [scope, setScope] = useState<'confirmed' | 'all'>('confirmed')
  const [busy, setBusy] = useState<'single' | 'per_chapter' | null>(null)

  const run = async (split: 'single' | 'per_chapter') => {
    setBusy(split)
    try {
      await submissionApi.export(novelId, scope, split)
    } catch {
      toast.error('导出失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        导出的正文会自动去掉模型附在章末的「接下来可以这样发展：A/B/C」这类选项。
      </p>
      <div>
        <label className="text-sm font-medium">导出范围</label>
        <div className="mt-2 flex gap-2">
          {([['confirmed', '仅已确认章节'], ['all', '全部（含草稿）']] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setScope(key)}
              className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                scope === key ? 'bg-primary/10 text-primary border-primary/40' : 'hover:bg-muted'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => run('single')}
          disabled={busy !== null}
          className="flex items-center gap-2 text-sm px-3 py-2 border rounded-lg hover:bg-muted disabled:opacity-50"
        >
          {busy === 'single' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
          整本 txt
        </button>
        <button
          onClick={() => run('per_chapter')}
          disabled={busy !== null}
          className="flex items-center gap-2 text-sm px-3 py-2 border rounded-lg hover:bg-muted disabled:opacity-50"
        >
          {busy === 'per_chapter' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileArchive className="w-4 h-4" />}
          分章 zip
        </button>
      </div>
    </div>
  )
}

// ── 过审预检 ─────────────────────────────────────────────────────────────────
// 类别默认全不勾：这个工具也用来写 NSFW，检查必须是用户主动要才跑。

function CheckTab({ novelId }: { novelId: number }) {
  const qc = useQueryClient()
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [includeCustom, setIncludeCustom] = useState(true)
  const [scope, setScope] = useState<'confirmed' | 'all'>('all')
  const [result, setResult] = useState<SensitiveScanResult | null>(null)
  const [newWords, setNewWords] = useState('')

  const { data } = useQuery({
    queryKey: ['sensitive-words'],
    queryFn: submissionApi.sensitiveWords,
  })

  const scan = useMutation({
    mutationFn: () => submissionApi.scan(novelId, [...picked], scope, includeCustom),
    onSuccess: setResult,
    onError: () => toast.error('检查失败'),
  })

  const addWords = useMutation({
    mutationFn: () => submissionApi.addSensitiveWords(newWords),
    onSuccess: (r) => {
      setNewWords('')
      qc.invalidateQueries({ queryKey: ['sensitive-words'] })
      toast.success(r.added > 0 ? `已添加 ${r.added} 个词` : '没有新词')
    },
    onError: () => toast.error('添加失败'),
  })

  const toggle = (key: string) => {
    setPicked(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const nothingSelected = picked.size === 0 && (!includeCustom || (data?.custom.length ?? 0) === 0)

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        默认什么都不查。勾上要查的类别再点检查，结果只是提示，不会改动正文。
        写 NSFW 内容时不勾「色情露骨」即可。
      </p>

      <div className="space-y-2">
        {(data?.categories ?? []).map(c => (
          <label key={c.key} className="flex items-start gap-2.5 border rounded-lg p-2.5 cursor-pointer hover:bg-muted/40">
            <input type="checkbox" checked={picked.has(c.key)} onChange={() => toggle(c.key)} className="mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{c.label}<span className="text-xs text-muted-foreground ml-2">{c.word_count} 词</span></div>
              {c.hint && <div className="text-xs text-muted-foreground">{c.hint}</div>}
            </div>
          </label>
        ))}
        <label className="flex items-center gap-2.5 border rounded-lg p-2.5 cursor-pointer hover:bg-muted/40">
          <input type="checkbox" checked={includeCustom} onChange={e => setIncludeCustom(e.target.checked)} className="shrink-0" />
          <span className="text-sm font-medium">我的自定义词<span className="text-xs text-muted-foreground ml-2">{data?.custom.length ?? 0} 词</span></span>
        </label>
      </div>

      <div>
        <label className="text-sm font-medium">补充自定义词</label>
        <div className="mt-1 flex gap-2">
          <input
            value={newWords}
            onChange={e => setNewWords(e.target.value)}
            placeholder="可整段粘贴，换行/空格/逗号分隔"
            className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            onClick={() => addWords.mutate()}
            disabled={!newWords.trim() || addWords.isPending}
            className="text-sm px-3 py-2 border rounded-lg hover:bg-muted disabled:opacity-50"
          >
            添加
          </button>
        </div>
        {(data?.custom.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data!.custom.map(w => (
              <button
                key={w.id}
                onClick={async () => {
                  await submissionApi.deleteSensitiveWord(w.id)
                  qc.invalidateQueries({ queryKey: ['sensitive-words'] })
                }}
                title="点击删除"
                className="text-xs px-2 py-0.5 rounded bg-muted hover:bg-destructive/15 hover:text-destructive"
              >
                {w.word} ×
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <select
          value={scope}
          onChange={e => setScope(e.target.value as 'confirmed' | 'all')}
          className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none"
        >
          <option value="all">全部章节</option>
          <option value="confirmed">仅已确认</option>
        </select>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending || nothingSelected}
          title={nothingSelected ? '先勾选要检查的类别' : ''}
          className="flex items-center gap-2 text-sm px-3 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {scan.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldAlert className="w-4 h-4" />}
          开始检查
        </button>
      </div>

      {result && <ScanReport result={result} />}
    </div>
  )
}

function ScanReport({ result }: { result: SensitiveScanResult }) {
  return (
    <div className="border-t pt-3 space-y-2">
      <div className="text-sm">
        扫了 {result.scanned_chapters} 章、用了 {result.word_count} 个词，
        {result.total_hits === 0
          ? <span className="text-green-600 dark:text-green-400">没有命中</span>
          : <span className="text-amber-600 dark:text-amber-400">命中 {result.total_hits} 处</span>}
      </div>
      {result.chapters.map(ch => (
        <div key={ch.chapter_id} className="border rounded-lg p-2.5">
          <div className="text-sm font-medium">第{ch.number}章 {ch.title}<span className="text-xs text-muted-foreground ml-2">{ch.hits.length} 处</span></div>
          <div className="mt-1.5 space-y-1">
            {ch.hits.map((h, i) => (
              <div key={i} className="text-xs flex gap-2">
                <span className="shrink-0 px-1.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">{h.word}</span>
                <span className="text-muted-foreground truncate">{h.excerpt}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
