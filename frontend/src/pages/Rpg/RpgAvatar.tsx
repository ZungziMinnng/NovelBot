/** 角色头像。没图就用名字首字，保证状态栏里永远不出现空洞。
 *  酒馆那个 CardAvatar 写死了粉色，RPG 侧走主题色，所以各自一份。 */
export default function RpgAvatar({
  name, url, size = 'md', className = '',
}: {
  name: string
  url?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  const box = { sm: 'w-8 h-8 text-xs', md: 'w-11 h-11 text-base', lg: 'w-16 h-16 text-xl' }[size]

  if (url) {
    return (
      <img
        src={url}
        alt={name}
        className={`${box} rounded-lg object-cover ring-1 ring-primary/25 shrink-0 ${className}`}
      />
    )
  }
  return (
    <div
      className={`${box} rounded-lg shrink-0 flex items-center justify-center font-semibold
        bg-primary/15 text-primary ring-1 ring-primary/25 ${className}`}
    >
      {name.trim().slice(0, 1) || '?'}
    </div>
  )
}
