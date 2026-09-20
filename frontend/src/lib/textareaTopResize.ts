/**
 * 把输入框的拖拽手柄从右下角挪到上边缘。
 *
 * 原生手柄是浏览器画在 textarea 右下角的装饰，CSS 挪不动（::-webkit-resizer
 * 只能改样子、不能改位置），只能自己接管：把「本来能拖」的 textarea 标上
 * data-top-resize、关掉原生手柄，然后在上边缘那一条上接 mousedown 拖高度。
 *
 * 为什么全局装一份，而不是包个 <ResizableTextarea> 组件：项目里散着 40 多处
 * resize-y，逐个换要多套一层 div，flex 里的 flex-1 / grid 子项 / h-full 全得跟着
 * 调，为一条手柄不值当。何况「所有输入框一个样」本来就是全局行为，正合 index.css
 * 里那句话——一条规则全覆盖，不用逐个改 JSX。
 *
 * 认不认账看 computed style，不看 class：没写 resize 类的 textarea 浏览器默认
 * both、本来也能拖，得算进来；写了 resize-none 的是作者故意不让拖的（章节正文框
 * 那种撑满高度的），不能抢。
 */

/** 拖拽区最多这么高 */
const MAX_ZONE = 8
/** 上内边距挨着 0 时的最小拖拽区，太小了根本点不着 */
const MIN_ZONE = 4
/** 元素自己没写 min-height 时的兜底 */
const FALLBACK_MIN = 40

let dragging = false

/** 拖拽区取上内边距：再往下就是第一行文字，抢了就没法点进去落光标 */
function zoneOf(el: HTMLTextAreaElement) {
  const cs = getComputedStyle(el)
  const pad = parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop)
  return Math.min(MAX_ZONE, Math.max(MIN_ZONE, pad))
}

function takeOver(el: HTMLTextAreaElement) {
  if (el.dataset.topResize) return
  if (getComputedStyle(el).resize === 'none') return
  // 拖拽区高度顺手存在 dataset 里，省得每次 mousemove 都读一遍 computed style
  el.dataset.topResize = String(zoneOf(el))
  // 只动 style.resize，className 里那个 resize-y 留着：重新挂载后再扫一遍时，
  // 「作者本来让不让拖」还得从 class 上认
  el.style.resize = 'none'
}

function scan(root: ParentNode) {
  if (root instanceof HTMLTextAreaElement) takeOver(root)
  else root.querySelectorAll('textarea').forEach(t => takeOver(t as HTMLTextAreaElement))
}

function onMouseDown(e: MouseEvent) {
  const el = e.target
  if (!(el instanceof HTMLTextAreaElement) || !el.dataset.topResize) return

  const rect = el.getBoundingClientRect()
  if (e.clientY - rect.top > Number(el.dataset.topResize)) return

  // 不拦的话点在上边缘会顺手把光标落到第一行
  e.preventDefault()
  dragging = true

  const startY = e.clientY
  const startHeight = rect.height
  const minHeight = parseFloat(getComputedStyle(el).minHeight) || FALLBACK_MIN
  // 别拖到看不见底：最多占满可视高度再留一截
  const maxHeight = window.innerHeight - 80

  const onMove = (m: MouseEvent) => {
    // 往上拖变高。输入框多在页面底部（生成栏、游玩页的对话框），那里盒子变高
    // 是往上顶的，手感就是「把上边缘拎起来」
    const next = startHeight + (startY - m.clientY)
    el.style.height = `${Math.max(minHeight, Math.min(maxHeight, next))}px`
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    dragging = false
  }

  // 拖的时候光标得跟到底，滑出那条窄边也不能变回 text
  document.body.style.cursor = 'ns-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

let hinted: HTMLTextAreaElement | null = null

/** 鼠标进到上边缘那一条就把光标换成上下箭头。原生手柄没了，全靠这个提示能拖 */
function onMouseMove(e: MouseEvent) {
  if (dragging) return
  const el = e.target
  const target = el instanceof HTMLTextAreaElement && el.dataset.topResize ? el : null
  if (hinted && hinted !== target) hinted.style.cursor = ''
  hinted = target
  if (!target) return

  const inZone = e.clientY - target.getBoundingClientRect().top <= Number(target.dataset.topResize)
  const want = inZone ? 'ns-resize' : ''
  if (target.style.cursor !== want) target.style.cursor = want
}

/** 全局装一次。返回卸载函数——StrictMode 下 effect 会跑两遍，得能摘干净 */
export default function installTextareaTopResize() {
  scan(document)

  // 页面切来切去，textarea 都是 React 后挂上来的，只扫一次不够
  const observer = new MutationObserver(records => {
    records.forEach(r => r.addedNodes.forEach(n => {
      if (n instanceof HTMLElement) scan(n)
    }))
  })
  observer.observe(document.body, { childList: true, subtree: true })

  document.addEventListener('mousedown', onMouseDown, true)
  document.addEventListener('mousemove', onMouseMove, true)

  return () => {
    observer.disconnect()
    document.removeEventListener('mousedown', onMouseDown, true)
    document.removeEventListener('mousemove', onMouseMove, true)
  }
}
