import { Form, Input, InputNumber, Select, Switch } from 'antd'

export interface JsonSchema {
  type?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  enum?: any[]
  title?: string
  description?: string
  items?: JsonSchema
  format?: string
}

interface Props {
  schema?: JsonSchema | null
  value?: Record<string, any>
  onChange?: (v: Record<string, any>) => void
  /** Form.Item name 前缀，用于在父 Form 中嵌套绑定 */
  namePrefix?: (string | number)[]
  disabled?: boolean
}

/** JSON Schema → antd 表单（用于技能参数、工具参数）。 */
export default function JsonSchemaForm({ schema, namePrefix, disabled }: Props) {
  const props = schema?.properties || {}
  const required = new Set(schema?.required || [])
  const keys = Object.keys(props)
  if (keys.length === 0) {
    return <span style={{ color: '#999', fontSize: 12 }}>该 Schema 无参数定义</span>
  }
  const np = namePrefix || []

  return (
    <>
      {keys.map((key) => {
        const p = props[key] || {}
        const label = p.title || key
        const rules = required.has(key) ? [{ required: true, message: `请填写 ${label}` }] : []
        const common = { name: [...np, key] as any, label, rules, key }
        const ph = p.description || ''
        const type = p.type || (p.enum ? 'string' : 'string')

        if (p.enum) {
          return (
            <Form.Item {...common}>
              <Select disabled={disabled} placeholder={ph}
                options={p.enum.map((v) => ({ value: v, label: String(v) }))} />
            </Form.Item>
          )
        }
        if (type === 'boolean') {
          return <Form.Item {...common} valuePropName="checked"><Switch disabled={disabled} /></Form.Item>
        }
        if (type === 'integer' || type === 'number') {
          return <Form.Item {...common}><InputNumber disabled={disabled} style={{ width: '100%' }} placeholder={ph} /></Form.Item>
        }
        if (type === 'array') {
          const opts = p.items?.enum
          if (opts) {
            return (
              <Form.Item {...common}>
                <Select mode="multiple" disabled={disabled} placeholder={ph} options={opts.map((v) => ({ value: v, label: String(v) }))} />
              </Form.Item>
            )
          }
          return <Form.Item {...common}><Select mode="tags" disabled={disabled} placeholder={ph || '回车添加'} /></Form.Item>
        }
        if (p.format === 'textarea' || (p.title || '').includes('描述') || (p.description || '').includes('多行')) {
          return <Form.Item {...common}><Input.TextArea rows={3} disabled={disabled} placeholder={ph} /></Form.Item>
        }
        return <Form.Item {...common}><Input disabled={disabled} placeholder={ph} /></Form.Item>
      })}
    </>
  )
}
