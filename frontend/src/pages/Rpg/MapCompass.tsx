/** 地图右上角的方位：上北下南左西右东。纯装饰，不挡鼠标。作者端和玩家端共用，
 *  两边方位说法必须一致 */
export default function MapCompass() {
  return (
    <div className="absolute top-2 right-2 w-16 h-16 pointer-events-none text-muted-foreground/80">
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 64 64" fill="none" stroke="currentColor">
        <line x1="32" y1="14" x2="32" y2="50" strokeWidth="1.5" />
        <line x1="14" y1="32" x2="50" y2="32" strokeWidth="1.5" />
        <polygon points="32,10 28,18 36,18" fill="currentColor" stroke="none" />
      </svg>
      <span className="absolute top-0 left-1/2 -translate-x-1/2 text-[11px] font-medium leading-none">北</span>
      <span className="absolute bottom-0 left-1/2 -translate-x-1/2 text-[11px] leading-none">南</span>
      <span className="absolute left-0 top-1/2 -translate-y-1/2 text-[11px] leading-none">西</span>
      <span className="absolute right-0 top-1/2 -translate-y-1/2 text-[11px] leading-none">东</span>
    </div>
  )
}
