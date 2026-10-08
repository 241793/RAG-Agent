import { useEffect, useRef, useState } from 'react'
import { BulbOutlined, DownOutlined } from '@ant-design/icons'

interface Props {
  reasoning?: string
  /** 该消息是否仍在流式生成中 */
  streaming?: boolean
}

/** 模型思考过程块：流式中默认展开、实时追加；结束后默认收起（可手动开合）。 */
export default function ReasoningBlock({ reasoning, streaming }: Props) {
  const [open, setOpen] = useState(true)
  const ended = useRef(false)

  useEffect(() => {
    if (streaming) {
      ended.current = false
      setOpen(true) // 流式中展开
    } else if (!ended.current) {
      setOpen(false) // 流式结束收起一次
      ended.current = true
    }
  }, [streaming])

  if (!reasoning) return null

  return (
    <div className="reasoning-block">
      <div className="reasoning-head" onClick={() => setOpen((o) => !o)}>
        <span>
          <BulbOutlined /> 思考过程{streaming ? '（进行中…）' : ''}
        </span>
        <DownOutlined style={{ fontSize: 11, transform: open ? 'rotate(180deg)' : undefined, transition: 'transform .2s' }} />
      </div>
      {open && <div className="reasoning-body">{reasoning}</div>}
    </div>
  )
}
