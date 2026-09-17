import type { RpgSave } from '@/api/client'
import { PANEL } from '../rpgUi'
import Empty from './Empty'

export default function SaveTab({
  saves, streaming, onSaveNow, onRestore, onDropSave,
}: {
  saves: RpgSave[]
  streaming: boolean
  onSaveNow: () => void
  onRestore: (save: RpgSave) => void
  onDropSave: (save: RpgSave) => void
}) {
  return (
    <>
      <button
        onClick={onSaveNow}
        disabled={streaming}
        className="w-full text-xs py-2 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/30
          hover:bg-primary/20 disabled:opacity-40"
      >
        存一个
      </button>
      {saves.length === 0 ? (
        <Empty>还没有存档。每跑一回合会自动拍一张。</Empty>
      ) : saves.map(save => (
        <div key={save.id} className={`${PANEL} p-3`}>
          <div className="flex items-baseline gap-2">
            <p className="text-sm font-medium flex-1 truncate">{save.label}</p>
            {save.kind === 'manual' && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                手动
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {new Date(save.created_at).toLocaleString()}
          </p>
          <div className="flex gap-1.5 mt-2">
            <button
              onClick={() => onRestore(save)}
              disabled={streaming}
              className="flex-1 text-xs py-1.5 rounded-lg bg-primary text-primary-foreground
                hover:opacity-90 disabled:opacity-40"
            >
              读档
            </button>
            <button
              onClick={() => onDropSave(save)}
              className="text-xs px-2.5 py-1.5 rounded-lg border text-muted-foreground hover:bg-muted"
            >
              删除
            </button>
          </div>
        </div>
      ))}
    </>
  )
}
