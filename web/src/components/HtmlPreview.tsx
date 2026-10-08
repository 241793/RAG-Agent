import { useState } from 'react'
import { Button, Drawer, Tooltip } from 'antd'
import { EyeOutlined } from '@ant-design/icons'

/**
 * HTML 在线预览（安全沙箱）。
 *
 * 安全红线：sandbox 只给 allow-scripts，绝不加 allow-same-origin
 * （二者同开会让 iframe 逃逸同源、读取 document.cookie / localStorage）。
 * 也不给 allow-top-navigation / allow-popups / allow-forms。
 * 内容仅来自 LLM 输出的 ```html 代码块，纯字符串，不经 dangerouslySetInnerHTML。
 */
export default function HtmlPreview({ html, title = 'HTML 预览' }: { html: string; title?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Tooltip title="预览效果">
        <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => setOpen(true)}>预览</Button>
      </Tooltip>
      <Drawer title={title} width={760} open={open} onClose={() => setOpen(false)} destroyOnClose>
        {open && (
          <iframe
            title={title}
            sandbox="allow-scripts"
            srcDoc={html}
            style={{ width: '100%', height: 'calc(100vh - 160px)', border: '1px solid #f0f0f0', borderRadius: 8 }}
          />
        )}
      </Drawer>
    </>
  )
}
