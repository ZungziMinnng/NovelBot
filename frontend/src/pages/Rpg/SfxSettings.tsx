import { playSfx, useSfxSettings } from './useSfx'

/**
 * 音效设置单独成块，而不是塞进某个通用设置面板：
 * 它最容易被当成「坏了」——文件得用户自己放，没放就是真的没声音
 */
export default function SfxSettings() {
  const { enabled, volume, setEnabled, setVolume } = useSfxSettings()

  return (
    <div className="space-y-2 rounded-xl border bg-muted/50 px-3 py-2.5 text-xs">
      <label className="flex cursor-pointer select-none items-center gap-2">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 cursor-pointer accent-primary"
          checked={enabled}
          onChange={e => {
            const next = e.target.checked
            setEnabled(next)
            // 开的时候立刻响一声，否则玩家要等到下一次掷骰才知道自己配好没有。
            // 点这一下本身就是解锁 autoplay 的交互，同步调用赶得上
            if (next) playSfx('dice')
          }}
        />
        <span className="text-xs font-medium">音效</span>
      </label>

      <div className={`flex items-center gap-2 ${enabled ? '' : 'opacity-40'}`}>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          disabled={!enabled}
          aria-label="音效音量"
          onChange={e => setVolume(Number(e.target.value))}
          className="flex-1 accent-primary disabled:cursor-not-allowed"
        />
        <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
          {Math.round(volume * 100)}%
        </span>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        音效文件得你自己准备：把六个 <code className="rounded bg-background px-1">.ogg</code> 丢进{' '}
        <code className="rounded bg-background px-1">public/sfx/</code>，文件名要跟 key 对上——
        dice、stat-up、stat-down、turn、enter、npc，缺哪个哪个场景就是静音。
        没放文件的话，这个开关开着也照样是安静的，不是 bug。
      </p>
    </div>
  )
}
