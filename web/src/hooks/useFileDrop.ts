import { useCallback, useRef, useState } from 'react'
import { message } from 'antd'

/** 拖入文件的落点类型：智能问答 = attachment，聊天室 = attachment，也可用于头像等。 */
export interface DropHandlers {
  /** 拖放容器 props：直接展开到最外层包裹元素上 */
  dropProps: {
    onDragEnter: (e: React.DragEvent) => void
    onDragOver: (e: React.DragEvent) => void
    onDragLeave: (e: React.DragEvent) => void
    onDrop: (e: React.DragEvent) => void
  }
  /** 是否正在拖拽悬浮（用于显示遮罩） */
  dragging: boolean
}

/**
 * 让某个区域支持「从外部拖入文件」。
 *
 * 实现要点：
 * - 只在 dragenter/over 时 preventDefault，浏览器才会触发 drop
 * - 用计数器抵消子元素间拖拽导致的反复 enter/leave（否则遮罩会闪烁）
 * - 只有真正携带文件的拖拽才响应（忽略页面内选中文字拖拽）
 *
 * @param onFiles 拖入文件后的回调（通常是上传）
 * @param accept 可选：MIME/扩展名白名单提示，不传则不限制
 */
export function useFileDrop(
  onFiles: (files: File[]) => void,
  accept?: string[],
): DropHandlers {
  const [dragging, setDragging] = useState(false)
  // 进入/离开计数：子元素间移动会连续触发 leave/enter，用计数保持稳定
  const depth = useRef(0)
  // 待处理的 files（drop 时同步取出后异步上传）
  const alive = useRef(true)

  const hasFiles = (e: React.DragEvent) => {
    const dt = e.dataTransfer
    if (!dt) return false
    // 某些浏览器在 dragover 阶段拿不到 files，靠 types 判断
    if (dt.types) return Array.from(dt.types).includes('Files')
    return (dt.files?.length || 0) > 0
  }

  const onDragEnter = useCallback((e: React.DragEvent) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    depth.current += 1
    setDragging(true)
  }, [])

  const onDragOver = useCallback((e: React.DragEvent) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    // 显式设置 copy，避免出现「禁止」图标
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDragLeave = useCallback((e: React.DragEvent) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setDragging(false)
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    depth.current = 0
    setDragging(false)
    const dt = e.dataTransfer
    const files = dt ? Array.from(dt.files || []) : []
    if (!files.length) return
    // 扩展名白名单（若提供）
    let picked = files
    if (accept && accept.length) {
      picked = files.filter((f) => {
        const ext = (f.name.split('.').pop() || '').toLowerCase()
        return accept.some((a) => {
          const rule = a.toLowerCase()
          if (rule.startsWith('.')) return ext === rule.slice(1)
          if (rule.endsWith('/*')) return f.type.startsWith(rule.slice(0, -1))
          return f.type === rule
        })
      })
      const rejected = files.length - picked.length
      if (rejected > 0) message.warning(`已忽略 ${rejected} 个不支持的文件`)
    }
    if (!picked.length) return
    if (alive.current) onFiles(picked)
  }, [onFiles, accept])

  return {
    dropProps: { onDragEnter, onDragOver, onDragLeave, onDrop },
    dragging,
  }
}
