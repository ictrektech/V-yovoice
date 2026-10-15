import { Children, Fragment, cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react'
import { useLanguage } from './index'
import { translateText } from './messages'
import type { Locale } from './vosLocale'

function translateNode(node: ReactNode, locale: Locale): ReactNode {
  if (typeof node === 'string') return translateText(node, locale)
  if (Array.isArray(node)) return node.map(child => translateNode(child, locale))
  if (!isValidElement(node)) return node
  if (typeof node.type !== 'string' && node.type !== Fragment) return node

  const element = node as ReactElement<Record<string, unknown>>
  if (element.props['data-i18n'] === 'off') return node
  const props: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(element.props)) {
    if (key === 'children') props.children = Children.map(value as ReactNode, child => translateNode(child, locale))
    else if (typeof value === 'string') props[key] = translateText(value, locale)
  }
  return cloneElement(element, props)
}

export function Localized({ children }: { children: ReactNode }) {
  const { locale } = useLanguage()
  return <>{Children.map(children, child => translateNode(child, locale))}</>
}
