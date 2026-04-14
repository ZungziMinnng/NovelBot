import { useState } from 'react'
import { X, ChevronRight, ChevronLeft, Loader2, BookOpen } from 'lucide-react'
import { novelsApi } from '@/api/client'

interface Props {
  onClose: () => void
  onComplete: (novelId: number) => void
}

const GENRES = ['古代权谋', '现代都市', '玄幻', '悬疑推理', '言情', '科幻', '历史', '其他']
const STYLES = ['严肃厉重', '轻快幽默', '悬念紧张', '细腻文艺', '热血激昂']
const LENGTHS = ['短篇（< 5万字）', '中篇（5-30万字）', '长篇（> 30万字）']
const LENGTH_VALUES = ['短篇', '中篇', '长篇']

export default function NovelWizard({ onClose, onComplete }: Props) {
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [novelId, setNovelId] = useState<number | null>(null)

  const [title, setTitle] = useState('')
  const [premise, setPremise] = useState('')
  const [genre, setGenre] = useState('古代权谋')
  const [length, setLength] = useState(1)
  const [style, setStyle] = useState('严肃厉重')

  const [rawSetting, setRawSetting] = useState('')
  const [rawRules, setRawRules] = useState('')
  const [worldPreview, setWorldPreview] = useState('')

  const [characters, setCharacters] = useState([
    { name: '', role: '主角', age: '', description: '' }
  ])

  const handleStep1 = async () => {
    if (!premise.trim()) return
    setLoading(true)
    try {
      const novel = await novelsApi.create({
        title: title || `《${premise.slice(0, 10)}...》`,
        premise,
        genre,
        target_length: LENGTH_VALUES[length],
        writing_style: style,
      })
      setNovelId(novel.id)
      setStep(2)
    } finally {
      setLoading(false)
    }
  }

  const handleSkip = async () => {
    if (!premise.trim()) return
    setLoading(true)
    try {
      const novel = await novelsApi.create({
        title: title || `《${premise.slice(0, 10)}...》`,
        premise,
        genre,
        target_length: LENGTH_VALUES[length],
        writing_style: style,
      })
      onComplete(novel.id)
    } finally {
      setLoading(false)
    }
  }

  const handleStep2 = async () => {
    if (!rawSetting.trim() || !novelId) return
    setLoading(true)
    try {
      const result = await novelsApi.wizardWorld(novelId, rawSetting, rawRules)
      setWorldPreview(result.core_setting)
      setStep(3)
    } finally {
      setLoading(false)
    }
  }

  const handleStep3 = async () => {
    if (!novelId) return
    const validChars = characters.filter(c => c.name.trim())
    if (validChars.length === 0) return
    setLoading(true)
    try {
      await novelsApi.wizardCharacters(novelId, validChars)
      setStep(4)
    } finally {
      setLoading(false)
    }
  }

  const handleStep4 = async () => {
    if (!novelId) return
    setLoading(true)
    try {
      await novelsApi.wizardOutline(novelId)
      onComplete(novelId)
    } finally {
      setLoading(false)
    }
  }

  const addCharacter = () =>
    setCharacters([...characters, { name: '', role: '配角', age: '', description: '' }])

  const updateChar = (i: number, k: string, v: string) =>
    setCharacters(characters.map((c, idx) => idx === i ? { ...c, [k]: v } : c))
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card rounded-2xl w-full max-w-2xl shadow-2xl">
        <div className="flex items-center justify-between p-6 border-b">
          <div>
            <h2 className="font-bold text-lg">新建小说</h2>
            <div className="flex items-center gap-1 mt-1">
              {[1,2,3,4].map(s => (
                <div key={s} className={`h-1 w-8 rounded-full transition-colors ${s <= step ? 'bg-primary' : 'bg-border'}`} />
              ))}
              <span className="text-xs text-muted-foreground ml-2">{step}/4</span>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-md hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6">
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-1 block">故事前提 *</label>
                <textarea
                  value={premise}
                  onChange={e => setPremise(e.target.value)}
                  placeholder="用一两句话描述你的故事核心..."
                  className="w-full border rounded-lg p-3 text-sm resize-none h-24 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">小说标题（可选）</label>
                <input
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="留空则自动生成"
                  className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">类型</label>
                <div className="flex flex-wrap gap-2">
                  {GENRES.map(g => (
                    <button key={g} onClick={() => setGenre(g)}
                      className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${genre === g ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                      {g}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium mb-2 block">目标长度</label>
                  <div className="space-y-1">
                    {LENGTHS.map((l, i) => (
                      <label key={l} className="flex items-center gap-2 cursor-pointer">
                        <input type="radio" checked={length === i} onChange={() => setLength(i)} />
                        <span className="text-sm">{l}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">写作风格</label>
                  <div className="space-y-1">
                    {STYLES.map(s => (
                      <label key={s} className="flex items-center gap-2 cursor-pointer">
                        <input type="radio" checked={style === s} onChange={() => setStyle(s)} />
                        <span className="text-sm">{s}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">描述你的世界观，AI 将为你扩写完整设定文档。</p>
              <div>
                <label className="text-sm font-medium mb-1 block">时代背景 *</label>
                <textarea
                  value={rawSetting}
                  onChange={e => setRawSetting(e.target.value)}
                  placeholder="例：架空古代，类似明朝中期，无魔法体系..."
                  className="w-full border rounded-lg p-3 text-sm resize-none h-20 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">核心规则/特殊设定（可选）</label>
                <textarea
                  value={rawRules}
                  onChange={e => setRawRules(e.target.value)}
                  placeholder="例：皇权衰弱，三大世家把持朝政..."
                  className="w-full border rounded-lg p-3 text-sm resize-none h-16 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              {worldPreview && (
                <div className="bg-muted rounded-lg p-4 text-sm text-muted-foreground">
                  <p className="font-medium text-foreground mb-1">AI 扩写预览：</p>
                  {worldPreview}
                </div>
              )}
            </div>
          )}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">添加主要角色，AI 将自动生成完整角色卡。</p>
              {characters.map((c, i) => (
                <div key={i} className="border rounded-lg p-4 space-y-3">
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">姓名 *</label>
                      <input value={c.name} onChange={e => updateChar(i, 'name', e.target.value)}
                        className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">定位</label>
                      <select value={c.role} onChange={e => updateChar(i, 'role', e.target.value)}
                        className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none">
                        {['主角','反派','配角','盟友'].map(r => <option key={r}>{r}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">年龄</label>
                      <input value={c.age} onChange={e => updateChar(i, 'age', e.target.value)}
                        placeholder="25" className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">一句话描述</label>
                    <input value={c.description} onChange={e => updateChar(i, 'description', e.target.value)}
                      placeholder="外表平庸内心坚韧..."
                      className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                  </div>
                </div>
              ))}
              <button onClick={addCharacter} className="w-full border border-dashed rounded-lg py-2 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors">
                + 添加角色
              </button>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              <div className="text-center py-4">
                <div className="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-4">
                  <BookOpen className="w-8 h-8 text-primary" />
                </div>
                <h3 className="font-semibold text-lg mb-2">准备生成大纲</h3>
                <p className="text-muted-foreground text-sm">
                  AI 将根据你的设定生成完整的章节大纲，这将作为后续创作的骨架。
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between p-6 border-t">
          <button
            onClick={() => step > 1 ? setStep(step - 1) : onClose()}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            {step === 1 ? '取消' : '上一步'}
          </button>
          <div className="flex items-center gap-2">
            {step === 1 && (
              <button
                onClick={handleSkip}
                disabled={loading || !premise.trim()}
                className="text-sm text-muted-foreground hover:text-foreground disabled:opacity-40 transition-colors px-3 py-2"
              >
                跳过，快速创建
              </button>
            )}
            <button
              onClick={() => {
                if (step === 1) handleStep1()
                else if (step === 2) handleStep2()
                else if (step === 3) handleStep3()
                else handleStep4()
              }}
              disabled={loading}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2 rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium text-sm"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {step === 4 ? '生成大纲并开始创作' : '下一步'}
              {!loading && step < 4 && <ChevronRight className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}