import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Pencil, Trash2, X, Loader2, FileText } from 'lucide-react'
import { novelsApi, novelNotesApi, type NovelNote } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'

export default function Notes() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: notes = [], isLoading } = useQuery({
    queryKey: ['notes', novelId],
    queryFn: () => novelNotesApi.list(novelId),
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formTitle, setFormTitle] = useState('')
  const [formContent, setFormContent] = useState('')
  const [saving, setSaving] = useState(false)

  const resetForm = () => {
    setFormTitle('')
    setFormContent('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (note: NovelNote) => {
    setEditingId(note.id)
    setFormTitle(note.title)
    setFormContent(note.content)
    setShowForm(true)
  }

  const handleSubmit = async () => {
    if (!formTitle.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await novelNotesApi.update(editingId, { title: formTitle.trim(), content: formContent })
      } else {
        await novelNotesApi.create({ novel_id: novelId, title: formTitle.trim(), content: formContent })
      }
      qc.invalidateQueries({ queryKey: ['notes', novelId] })
      resetForm()
    } finally { setSaving(false) }
  }

  const handleDelete = async (noteId: number) => {
    if (!confirm('确认删除该设定笔记？')) return
    await novelNotesApi.delete(noteId)
    qc.invalidateQueries({ queryKey: ['notes', novelId] })
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 补充设定</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {notes.length} 条设定 · 记录势力体系、修炼规则、阵营关系等补充世界观
          </p>
          {!showForm && (
            <button onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted transition-colors">
              <Plus className="w-3.5 h-3.5" /> 添加设定
            </button>
          )}
        </div>

        {showForm && (
          <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑设定' : '添加新设定'}</span>
              <button onClick={resetForm} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block">标题 *</label>
              <input value={formTitle} onChange={e => setFormTitle(e.target.value)}
                placeholder="例：各大势力分布、灵兽品阶体系"
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block">内容</label>
              <textarea value={formContent} onChange={e => setFormContent(e.target.value)} rows={6}
                placeholder="详细描述该设定的具体内容..."
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y" />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={resetForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSubmit} disabled={!formTitle.trim() || saving}
                className="text-sm px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingId ? '保存修改' : '添加'}
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : notes.length === 0 ? (
          <div className="text-center py-20 text-muted-foreground">
            <p>暂无补充设定，点击「添加设定」开始</p>
          </div>
        ) : (
          <div className="space-y-2">
            {notes.map(note => (
              <div key={note.id} className="border rounded-lg px-4 py-3">
                <div className="flex items-start gap-3">
                  <FileText className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{note.title}</span>
                    {note.content && (
                      <p className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap line-clamp-4">{note.content}</p>
                    )}
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button onClick={() => startEdit(note)} className="p-1.5 rounded hover:bg-muted" title="编辑">
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => handleDelete(note.id)} className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30" title="删除">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
