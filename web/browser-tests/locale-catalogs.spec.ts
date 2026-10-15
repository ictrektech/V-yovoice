import { test, expect } from '@playwright/test';
import en from '../src/shared/i18n/catalogs/en.json' with { type: 'json' };
import zhCN from '../src/shared/i18n/catalogs/zh-cn.json' with { type: 'json' };
import zhTW from '../src/shared/i18n/catalogs/zh-tw.json' with { type: 'json' };
import { resolveInitialUiLocale, parseUiLocale } from '../src/shared/i18n/locale';
import { createDraft } from '../src/shared/workbench';

test('三语言词条完整且保留 ICU 参数和技术标识', () => {
  for (const catalog of [zhCN, zhTW]) {
    expect(Object.keys(catalog).sort()).toEqual(Object.keys(en).sort());
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(catalog[key].defaultMessage.length).toBeGreaterThan(0);
      const parameters = (value: string) => [...value.matchAll(/\{([a-zA-Z][\w]*)[},]/g)].map(match => match[1]).sort();
      expect(parameters(catalog[key].defaultMessage)).toEqual(parameters(en[key].defaultMessage));
    }
  }
  expect(zhTW['@vvoice.nav.api'].defaultMessage).toBe('API 文件');
});

test('繁体地区和显式偏好独立于语音语言', () => {
  for (const tag of ['zh-TW', 'zh-HK', 'zh-Hant']) expect(resolveInitialUiLocale(tag)).toBe('zh-TW');
  expect(resolveInitialUiLocale('zh-CN')).toBe('zh-CN');
  expect(parseUiLocale('zh-TW')).toBe('zh-TW');
  expect(createDraft(false, 'zh-TW').language).toBe('zh');
  expect(createDraft(true, 'zh-TW').text).toContain('陽光');
});
