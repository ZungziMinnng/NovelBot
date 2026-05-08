import { useState } from 'react'
import { X, Loader2, Play, AlertTriangle, AlertCircle, Info, Clock, BookX, HelpCircle } from 'lucide-react'
import { generationApi, type ReviewIssue, type ReviewResult } from '@/api/client'
import toast from 'react-hot-toast'

const ISSUE_TYPE_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  plot_contradiction:       { label: '情节矛盾', color: 'text-red-600 bg-red-50 dark:bg-red-900/30 dark:text-red-400', icon: AlertTriangle },
  character_inconsistency:  { label: '角色不一致', color: 'text-orange-600 bg-orange-50 dark:bg-orange-900/30 dark:text-orange-400', icon: AlertCircle },
  forgotten_thread:         { label: '遗忘伏笔', color: 'text-blue-600 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-400', icon: BookX },
  timeline_error:           { label: '时间线错误', color: 'text-purple-600 bg-purple-50 dark:bg-purple-900/30 dark:text-purple-400', icon: Clock },
  setting_violation:        { label: '设定违背', color: 'text-yellow-600 bg-yellow-50 dark:bg-yellow-900/30 dark:text-yellow-400', icon: Info },
  other:                    { label: '其他', color: 'text-gray-600 bg-gray-50 dark:bg-gray-900/30 dark:text-gray-400', icon: HelpCircle },
}

const SEVERITY_BADGE: Record<string, string> = {
  high: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  medium: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  low: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
}

interface ReviewModalProps {
  novelId: number
  result: ReviewResult | null
  onResult: (r: ReviewResult | null) => void
  onClose: () => void
}

export default function ReviewModal({ novelId, result, onResult, onClose }: ReviewModalProps) {
  const [loading, setLoading] = useState(false)

  const handleStart = async () => {
    setLoading(true)
    onResult(null)
    try {
      const data = await generationApi.review(novelId)
      onResult(data)
      if (data.issues.length === 0) {
        toast.success('审查完成，未发现问题')
      } else {
        toast.success(`审查完成，发现 ${data.issues.length} 个问题`)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '审查失败'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  const grouped = result ? groupByType(result.issues) : {}

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-y-4 left-1/2 -translate-x-1/2 w-full max-w-2xl bg-background border rounded-xl shadow-2xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
          <h2 className="text-base font-semibold">全文审查</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Start button */}
          {!loading && !result && (
            <div className="text-center py-12">
              <p className="text-sm text-muted-foreground mb-4">
                将全部章节分批（每20章一批）发送给审查模型，检测全局一致性问题。
              </p>
              <button
                onClick={handleStart}
                className="inline-flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90"
              >
                <Play className="w-4 h-4" /> 开始审查
              </button>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-sm text-muted-foreground">正在分批审查全文，每20章一批并行处理...</p>
            </div>
          )}

          {/* Results */}
          {result && (
            <div className="space-y-4">
              {/* Summary */}
              <div className="flex items-center gap-4 p-3 rounded-lg bg-muted/30">
                <div className="text-center">
                  <p className="text-2xl font-bold">{result.issues.length}</p>
                  <p className="text-[10px] text-muted-foreground">问题数</p>
                </div>
                <div className="flex-1 text-xs text-muted-foreground space-y-0.5">
                  <p>审查 {result.chapter_count} 章 / {result.word_count.toLocaleString()} 字</p>
                  <p>模型: {result.model}</p>
                  <p>Token: {result.input_tokens.toLocaleString()} in / {result.output_tokens.toLocaleString()} out</p>
                </div>
                <button
                  onClick={handleStart}
                  disabled={loading}
                  className="px-3 py-1.5 text-xs border rounded-lg hover:bg-muted"
                >
                  重新审查
                </button>
              </div>

              {/* Issues by type */}
              {result.issues.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  未发现一致性问题
                </div>
              ) : (
                Object.entries(grouped).map(([type, issues]) => {
                  const cfg = ISSUE_TYPE_CONFIG[type] || ISSUE_TYPE_CONFIG.other
                  const Icon = cfg.icon
                  return (
                    <div key={type}>
                      <div className="flex items-center gap-2 mb-2">
                        <Icon className={`w-4 h-4 ${cfg.color.split(' ')[0]}`} />
                        <span className="text-sm font-medium">{cfg.label}</span>
                        <span className="text-xs text-muted-foreground">({issues.length})</span>
                      </div>
                      <div className="space-y-2 ml-6">
                        {issues.map((issue, i) => (
                          <div key={i} className={`p-3 rounded-lg border ${cfg.color}`}>
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`text-[10px] px-1.5 py-0.5 rounded ${SEVERITY_BADGE[issue.severity] || SEVERITY_BADGE.low}`}>
                                {issue.severity === 'high' ? '严重' : issue.severity === 'medium' ? '中等' : '轻微'}
                              </span>
                              {issue.chapters.length > 0 && (
                                <span className="text-[10px] text-muted-foreground">
                                  第 {issue.chapters.join('、')} 章
                                </span>
                              )}
                            </div>
                            <p className="text-xs">{issue.description}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function groupByType(issues: ReviewIssue[]): Record<string, ReviewIssue[]> {
  const grouped: Record<string, ReviewIssue[]> = {}
  for (const issue of issues) {
    const type = issue.type || 'other'
    if (!grouped[type]) grouped[type] = []
    grouped[type].push(issue)
  }
  return grouped
}
