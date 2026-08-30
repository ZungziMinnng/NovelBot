/** 角色卡头像。没传图时用名字首字 + 紫粉渐变占位，保证列表页永远不出现空洞 */
export default function CardAvatar({
  name, url, size = 'md', className = '',
}: {
  name: string
  url?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  const box = { sm: 'w-8 h-8 text-xs', md: 'w-14 h-14 text-lg', lg: 'w-20 h-20 text-2xl' }[size]

  if (url) {
    return (
      <img
        src={url}
        alt={name}
        className={`${box} rounded-xl object-cover ring-1 ring-pink-500/25 shrink-0 ${className}`}
      />
    )
  }
  return (
    <div
      className={`${box} rounded-xl shrink-0 flex items-center justify-center font-semibold
        bg-gradient-to-br from-pink-500/35 to-fuchsia-700/25 text-pink-200
        ring-1 ring-pink-500/25 ${className}`}
    >
      {name.trim().slice(0, 1) || '?'}
    </div>
  )
}
