import { useEffect, useMemo, useState } from 'react'
import type { RefObject } from 'react'

export interface TimelineItem {
  index: number
  role: 'user' | 'assistant'
  text: string
}

interface Turn {
  /** 该轮首条消息在 msgs 中的下标（跳转锚点） */
  anchor: number
  role: 'user' | 'assistant'
  text: string
}

interface Props {
  items: TimelineItem[]
  /** 消息滚动容器（IntersectionObserver 的 root） */
  scrollRoot: RefObject<HTMLElement | null>
  onJump: (index: number) => void
  /** 消息数少于该值时不显示 */
  minCount?: number
}

const ROLE_LABEL: Record<string, string> = { user: '我', assistant: 'AI' }

/**
 * 消息区右侧迷你时间轴（元宝风格）：
 * 每条用户提问一根小横线，hover 显示预览气泡，点击跳转到该轮，当前视口内的一轮高亮。
 */
export default function MessageTimeline({ items, scrollRoot, onJump, minCount = 6 }: Props) {
  const [hover, setHover] = useState<number | null>(null)
  const [active, setActive] = useState<number | null>(null)

  // 组装轮次：遇 user 开新轮；assistant 归入当前轮（首条即 assistant 时独立成轮）
  const turns = useMemo<Turn[]>(() => {
    const out: Turn[] = []
    for (const it of items) {
      if (it.role === 'user' || out.length === 0) {
        out.push({ anchor: it.index, role: it.role, text: it.text })
      } else if (out[out.length - 1].role !== 'user') {
        out[out.length - 1] = { ...out[out.length - 1], text: it.text }
      }
    }
    return out
  }, [items])

  // 随滚动标记当前视口内最靠上的一条消息，映射到所在轮
  useEffect(() => {
    const root = scrollRoot.current
    if (!root) return
    const els = items
      .map((it) => document.getElementById(`msg-${it.index}`))
      .filter((e): e is HTMLElement => !!e)
    if (!els.length) return
    const visible = new Map<number, number>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const idx = Number((e.target as HTMLElement).id.replace('msg-', ''))
          if (e.isIntersecting) visible.set(idx, (e.target as HTMLElement).getBoundingClientRect().top)
          else visible.delete(idx)
        }
        if (visible.size) {
          const top = [...visible.entries()].sort((a, b) => a[1] - b[1])[0][0]
          setActive(top)
        }
      },
      { root, rootMargin: '-6% 0px -68% 0px', threshold: 0 },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [items, scrollRoot])

  if (items.length < minCount) return null

  const activeTurn = turns.findIndex((t, i) => {
    const next = turns[i + 1]
    return active != null && active >= t.anchor && (!next || active < next.anchor)
  })

  return (
    <div
      style={{
        flex: '0 0 auto', width: 26, height: '100%',
        display: 'flex', flexDirection: 'column', alignItems: 'flex-end', justifyContent: 'center',
        paddingRight: 5, zIndex: 5,
      }}
    >
      <div
        className="msg-timeline-col"
        style={{
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 9,
          maxHeight: '100%', overflowY: 'auto', paddingLeft: 12, paddingRight: 5,
        }}
      >
        {turns.map((t, i) => {
          const on = hover === i
          const act = activeTurn === i
          return (
            <div
              key={t.anchor}
              className="msg-timeline-row"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((h) => (h === i ? null : h))}
              onClick={() => onJump(t.anchor)}
              style={{ position: 'relative', display: 'flex', justifyContent: 'flex-end', cursor: 'pointer' }}
            >
              <div
                style={{
                  width: on || act ? 18 : 12,
                  height: on ? 4 : act ? 3.5 : 2.5,
                  borderRadius: 3,
                  background: on ? '#2563eb' : act ? '#4b8bf5' : t.role === 'user' ? '#c2c8d0' : '#d8dce2',
                  transition: 'width .15s, background .15s, height .15s',
                }}
              />
              {on && (
                <div
                  style={{
                    position: 'absolute', right: 'calc(100% + 8px)', top: '50%', transform: 'translateY(-50%)',
                    width: 244, maxWidth: 244, background: '#fff', border: '1px solid #eef0f3',
                    borderRadius: 10, boxShadow: '0 6px 20px rgba(16,24,40,0.12)',
                    padding: '8px 10px', pointerEvents: 'none', zIndex: 20,
                  }}
                >
                  <div style={{ fontSize: 12, color: '#2563eb', fontWeight: 600, marginBottom: 3 }}>
                    {ROLE_LABEL[t.role] || t.role}
                  </div>
                  <div style={{ fontSize: 12.5, color: '#4b5563', lineHeight: 1.5, maxHeight: 96, overflow: 'hidden' }}>
                    {(t.text || '(空)').slice(0, 90)}
                    {(t.text || '').length > 90 ? '…' : ''}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
