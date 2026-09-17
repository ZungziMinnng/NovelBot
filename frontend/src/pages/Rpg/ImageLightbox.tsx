import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

/** 看立绘原图。立绘是 2:3 竖图，头像那个方形 object-cover 只露得出脸。 */
export default function ImageLightbox({ url, alt, onClose }: {
  url: string
  alt: string
  onClose: () => void
}) {
  // 同 CharacterForm：挂 body，否则被 sticky 页头压住
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-6"
      onClick={onClose}
    >
      <img
        src={url}
        alt={alt}
        onClick={e => e.stopPropagation()}
        className="max-h-full max-w-full rounded-xl object-contain shadow-2xl"
      />
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-lg bg-black/50 text-white hover:bg-black/70"
      >
        <X className="w-5 h-5" />
      </button>
    </div>,
    document.body,
  )
}
