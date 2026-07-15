import { useState } from 'react'
import { X, RefreshCw, Loader2, Trash2, Check, Pencil } from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import toast from 'react-hot-toast'

interface CharacterCardModalProps {
  character: Character
  onClose: () => void
  onUpdated: (char: Character) => void
  onDeleted: (charId: number) => void
}

export default function CharacterCardModal({ character, onClose, onUpdated, onDeleted }: CharacterCardModalProps) {
  const sheet = (character.full_sheet || {}) as Record<string, unknown>
  const [editing, setEditing] = useState(false)
  const [rerolling, setRerolling] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Editable fields
  const [personality, setPersonality] = useState(String(sheet.personality || ''))
  const [skills, setSkills] = useState(Array.isArray(sheet.skills) ? (sheet.skills as string[]).join('、') : String(sheet.skills || ''))
  const [appearance, setAppearance] = useState(String(sheet.appearance || ''))
  const [speechStyle, setSpeechStyle] = useState(String(sheet.speech_style || ''))

  const handleReroll = async () => {
    setRerolling(true)
    try {
      const updated = await charactersApi.generateSheet(character.id)
      const s = (updated.full_sheet || {}) as Record<string, unknown>
      setPersonality(String(s.personality || ''))
      setSkills(Array.isArray(s.skills) ? (s.skills as string[]).join('、') : String(s.skills || ''))
      setAppearance(String(s.appearance || ''))
      setSpeechStyle(String(s.speech_style || ''))
      onUpdated(updated)
      toast.success('已重新生成角色卡')
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '重新生成失败')
    } finally { setRerolling(false) }
  }

  const handleSave = async () => {
    const newSheet: Record<string, unknown> = {
      ...sheet,
      personality,
      skills: skills.split(/[,，、]/).map(s => s.trim()).filter(Boolean),
      appearance,
      speech_style: speechStyle,
    }
    try {
      const updated = await charactersApi.update(character.id, { full_sheet: newSheet })
      onUpdated(updated as unknown as Character)
      setEditing(false)
      toast.success('角色卡已更新')
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    }
  }

  const handleDelete = async () => {
    if (!confirm(`确认删除角色「${character.name}」？此操作不可撤销。`)) return
    setDeleting(true)
    try {
      await charactersApi.delete(character.id)
      onDeleted(character.id)
      toast.success(`已删除「${character.name}」`)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败')
      setDeleting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="bg-background rounded-xl shadow-xl max-h-[90vh] overflow-y-auto w-[720px] mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-background border-b px-5 py-3 flex items-center gap-3 z-10 rounded-t-xl">
          <h2 className="font-bold text-base flex-1">{character.name} · 角色卡</h2>
          <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">{character.role}</span>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 transition-colors"
            title="删除角色"
          >
            {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
          </button>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-4">
          {/* Meta row */}
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <span>年龄：{character.age || '未设置'}</span>
            <span>简介：{character.description || '无'}</span>
          </div>

          {/* Actions bar */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setEditing(!editing)}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                editing ? 'bg-primary text-primary-foreground border-primary' : 'hover:bg-muted'
              }`}
            >
              <Pencil className="w-3 h-3" />
              {editing ? '编辑中' : '编辑'}
            </button>
            <button
              onClick={handleReroll}
              disabled={rerolling}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border hover:bg-muted transition-colors disabled:opacity-50"
            >
              {rerolling ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              重新抽卡
            </button>
            {editing && (
              <button
                onClick={handleSave}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90"
              >
                <Check className="w-3 h-3" /> 保存修改
              </button>
            )}
          </div>

          {/* Personality */}
          <Field
            label="性格"
            value={personality}
            editing={editing}
            onChange={setPersonality}
          />

          {/* Skills */}
          <Field
            label="技能"
            value={skills}
            editing={editing}
            onChange={setSkills}
            placeholder="多个技能用顿号或逗号分隔"
          />

          {/* Appearance */}
          <Field
            label="外貌"
            value={appearance}
            editing={editing}
            onChange={setAppearance}
            multiline
          />

          {/* Speech Style */}
          <Field
            label="说话风格"
            value={speechStyle}
            editing={editing}
            onChange={setSpeechStyle}
          />
        </div>
      </div>
    </div>
  )
}

function Field({
  label, value, editing, onChange, multiline, placeholder,
}: {
  label: string
  value: string
  editing: boolean
  onChange: (v: string) => void
  multiline?: boolean
  placeholder?: string
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground mb-1 block">{label}</label>
      {editing ? (
        multiline ? (
          <textarea
            value={value}
            onChange={e => onChange(e.target.value)}
            rows={4}
            placeholder={placeholder}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y"
          />
        ) : (
          <input
            value={value}
            onChange={e => onChange(e.target.value)}
            placeholder={placeholder}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
        )
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{value || '（空）'}</p>
      )}
    </div>
  )
}
