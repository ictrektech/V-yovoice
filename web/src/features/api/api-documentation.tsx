import { VStack } from '@astryxdesign/core/Layout';
import { useLocale, useTranslator } from '@astryxdesign/core/i18n';
import { applyServiceTheme } from './service-theme';

// 复用兼容服务的完整文档与多语言词库，独立文档视图不卸载编辑器或丢失草稿。
export function ApiDocumentation() {
  const locale = useLocale();
  const t = useTranslator();
  return <VStack gap={3} style={{ flex: 1, minHeight: 0 }} data-testid="api-documentation">
    <header><h1>{t('@vvoice.nav.api')}</h1><p>{t('@vvoice.api.hint')}</p></header>
    <iframe onLoad={applyServiceTheme} title={t('@vvoice.nav.api')} src={`./service/?page=api&standalone=1&locale=${encodeURIComponent(locale === 'en' ? 'en-US' : locale)}`} style={{ width: '100%', flex: 1, minHeight: 0, border: 0 }} />
  </VStack>;
}
