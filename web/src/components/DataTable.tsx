import { Table } from 'antd'
import type { TableProps } from 'antd'
import EmptyState from './EmptyState'

interface Props<T> extends TableProps<T> {
  /** 数据为空时的提示文案 */
  emptyText?: string
}

/**
 * 统一表格：默认加上横向滚动（窄屏防溢出）、统一空态。
 * 用法与 antd Table 一致，只是把这两个高频遗漏项变成默认。
 */
export default function DataTable<T extends object>({ emptyText, scroll, locale, ...rest }: Props<T>) {
  return (
    <Table<T>
      {...rest}
      scroll={scroll ?? { x: 'max-content' }}
      locale={{ emptyText: <EmptyState description={emptyText} />, ...locale }}
    />
  )
}
