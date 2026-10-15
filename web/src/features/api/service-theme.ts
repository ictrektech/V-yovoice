import type { SyntheticEvent } from 'react';

// 同源兼容页复用工作台主题令牌，保留既有表单及接口行为。
export function applyServiceTheme(event: SyntheticEvent<HTMLIFrameElement>) {
  const root = event.currentTarget.contentDocument?.documentElement;
  if (!root) return;
  const theme = getComputedStyle(document.documentElement);
  for (let index = 0; index < theme.length; index++) {
    const name = theme[index];
    if (/^--(color-|spacing-|radius-|font-|border-|app-)/.test(name)) root.style.setProperty(name, theme.getPropertyValue(name));
  }
  root.dataset.workbenchTheme = 'true';
}
