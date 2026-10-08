import { Modal } from 'antd'
import type { ModalProps } from 'antd'

interface Props extends ModalProps {
  /** 宽度档位：sm=520 / md=640 / lg=820。默认 md。 */
  size?: 'sm' | 'md' | 'lg'
}

const WIDTH = { sm: 520, md: 640, lg: 820 }

/** 统一 Modal：规范的宽度档位 + 默认 destroyOnClose。 */
export default function FormModal({ size = 'md', width, destroyOnClose, ...rest }: Props) {
  return (
    <Modal {...rest} width={width ?? WIDTH[size]} destroyOnClose={destroyOnClose ?? true} />
  )
}
