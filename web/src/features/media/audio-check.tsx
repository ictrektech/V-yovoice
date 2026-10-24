import { Button } from '@astryxdesign/core/Button';
import { useTranslator } from '@astryxdesign/core/i18n';
import { TriangleAlert } from 'lucide-react';
import { formatTime, type AudioCheck, type AudioIssue } from '../../shared/workbench';

// 直流偏移对听感影响很小，只给助手看，不在界面上提醒。
const shown = (issue: AudioIssue) => issue.code !== 'dc';

/** 体检里值得提醒的问题；没有时返回空数组。 */
export const audioIssues = (check?: AudioCheck) => check?.issues?.filter(shown) ?? [];

/**
 * 生成结果的体检提醒：有削波、截断、长静音等问题时显示一个警告图标，悬停或点按看具体问题与时间。
 * 体检只做测量，不用模型，所以只提示“可能有问题”，由用户试听后决定是否重新生成。
 */
export function AudioCheckBadge({ check, className }: { check?: AudioCheck; className?: string }) {
  const t = useTranslator();
  const issues = audioIssues(check);
  if (!issues.length) return null;
  const describe = (issue: AudioIssue) => t(`@yovoice.check.${issue.code}`, {
    at: formatTime(issue.at), end: formatTime(issue.end ?? issue.at), count: issue.count ?? 1, loudness: check!.loudness.toFixed(1),
  });
  const detail = t('@yovoice.check.summary', { issues: issues.map(describe).join(t('@yovoice.check.separator')) });
  return <Button className={className ? `audio-check ${className}` : 'audio-check'} size="sm" variant="ghost" isIconOnly icon={<TriangleAlert />} label={detail} tooltip={detail} data-testid="audio-check" />;
}
