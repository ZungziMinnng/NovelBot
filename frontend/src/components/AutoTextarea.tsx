import { forwardRef, type TextareaHTMLAttributes } from 'react'

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** 最少显示行数，内容超出时自动增高 */
  minRows?: number
}

/** 高度随内容自动增长的 textarea，支持手动上下拖拽（resize-y） */
const AutoTextarea = forwardRef<HTMLTextAreaElement, Props>(
  function AutoTextarea({ minRows = 5, value, className = '', ...rest }, ref) {
    const text = typeof value === 'string' ? value : value == null ? '' : String(value)
    const rows = Math.max(minRows, text.split('\n').length + 1)
    return (
      <textarea
        ref={ref}
        value={value}
        rows={rows}
        className={`resize-y ${className}`}
        {...rest}
      />
    )
  },
)

export default AutoTextarea
