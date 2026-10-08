import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Button, message, Tooltip } from 'antd'
import { CopyOutlined, CheckOutlined } from '@ant-design/icons'
// 按需注册语言（避免全量打包）
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import HtmlPreview from './HtmlPreview'

const LANGS: Record<string, unknown> = {
  tsx, typescript, typescriptreact: typescript, javascript, jsx, json, python,
  bash, shell: bash, sh: bash, css, html: markup, xml: markup, sql, yaml, yml: yaml,
  markdown, md: markdown, java, go,
}
for (const [name, def] of Object.entries(LANGS)) {
  try { SyntaxHighlighter.registerLanguage(name, def as any) } catch { /* ignore dup */ }
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(code)
    setCopied(true); message.success('已复制')
    setTimeout(() => setCopied(false), 1500)
  }
  const isHtml = language === 'html' || language === 'htm'
  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span className="code-lang">{language || 'text'}</span>
        {isHtml && <HtmlPreview html={code} />}
        <Tooltip title={copied ? '已复制' : '复制'}>
          <Button size="small" type="text" icon={copied ? <CheckOutlined /> : <CopyOutlined />} onClick={copy} />
        </Tooltip>
      </div>
      <SyntaxHighlighter language={language || 'text'} style={oneLight} PreTag="div" customStyle={{ margin: 0, borderRadius: 8, fontSize: 13 }}>
        {code}
      </SyntaxHighlighter>
    </div>
  )
}

/** 统一 Markdown 渲染：GFM + 代码高亮 + 复制 + HTML 预览。 */
const MarkdownBody = memo(function MarkdownBody({ content, className }: { content: string; className?: string }) {
  return (
    <div className={className || 'md-body'}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className: cls, children, ...rest } = props as any
            const m = /language-(\w+)/.exec(cls || '')
            const raw = String(children ?? '')
            const isInline = !m && !raw.includes('\n')
            if (isInline) return <code className="md-inline-code" {...rest}>{children}</code>
            return <CodeBlock language={m?.[1] || ''} code={raw.replace(/\n$/, '')} />
          },
          a(props) {
            return <a {...props} target="_blank" rel="noreferrer noopener" />
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})

export default MarkdownBody
