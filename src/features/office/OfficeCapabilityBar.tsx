/**
 * OfficeCapabilityBar — Round A P6: 环境能力徽章条。
 *
 * 挂在 Office 页 header 下方，展示本机转换器 / 可选依赖的可用状态：
 *   PDF 导出（LibreOffice 或 Word COM）· 图片压缩（Pillow）· 公式求值
 *   （formulas）。
 * 缺失项显示为灰色徽章 + hover 提示安装指引（按平台给出对应命令/下载
 * 页），替代"点了导出才发现没装"的事后失败 toast。「重新检测」按钮带
 * force=true 跳过后端 30s 缓存 —— 用户装完 LibreOffice 立即能刷出来。
 *
 * 探测失败（后端未启动等）时整条隐藏 —— 能力条是辅助信息，绝不能挡住
 * 页面主流程。
 */

import { CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeCapabilities } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface OfficeCapabilityBarProps {
  /** 探测结果回传给页面（预览面板据此隐藏高保真开关）。 */
  onCapabilities?: (caps: OfficeCapabilities) => void;
}

interface BadgeSpec {
  key: string;
  ok: boolean;
  label: string;
  hint: string;
}

/** 平台相关的 LibreOffice 安装指引 i18n key；Windows 上额外提示 MS Word 亦可。 */
function installHintKey(
  platform: string,
): 'office.caps.install.pdf.win' | 'office.caps.install.pdf.mac' | 'office.caps.install.pdf.linux' {
  if (platform === 'win32') return 'office.caps.install.pdf.win';
  if (platform === 'darwin') return 'office.caps.install.pdf.mac';
  return 'office.caps.install.pdf.linux';
}

export function OfficeCapabilityBar({ onCapabilities }: OfficeCapabilityBarProps) {
  const { t } = useI18n();
  const [caps, setCaps] = useState<OfficeCapabilities | null>(null);
  const [probing, setProbing] = useState(false);

  const probe = useCallback(
    async (force: boolean) => {
      setProbing(true);
      try {
        const result = await officeApi.getCapabilities(force);
        setCaps(result);
        onCapabilities?.(result);
      } catch {
        // 探测失败 → 整条隐藏（caps 维持 null）。辅助信息不阻塞页面。
        setCaps(null);
      } finally {
        setProbing(false);
      }
    },
    [onCapabilities],
  );

  useEffect(() => {
    void probe(false);
  }, [probe]);

  if (!caps) return null;

  const badges: BadgeSpec[] = [
    {
      key: 'pdf',
      ok: caps.pdf_export_available,
      label: t('office.caps.pdf'),
      hint: caps.pdf_export_available
        ? caps.soffice_available
          ? `LibreOffice: ${caps.soffice_path ?? ''}`
          : 'MS Word COM'
        : t(installHintKey(caps.platform)),
    },
    {
      key: 'image',
      ok: caps.pillow_available,
      label: t('office.caps.image'),
      hint: caps.pillow_available ? 'Pillow' : t('office.caps.install.pillow'),
    },
    {
      key: 'formula',
      ok: caps.formulas_available,
      label: t('office.caps.formula'),
      hint: caps.formulas_available ? 'formulas' : t('office.caps.install.formulas'),
    },
  ];

  return (
    <div
      className="flex items-center gap-2 flex-wrap text-xs"
      data-testid="office-capability-bar"
    >
      {badges.map((b) => (
        <span
          key={b.key}
          title={b.hint}
          data-testid={`office-cap-${b.key}`}
          data-ok={b.ok}
          className={`inline-flex items-center gap-1 px-2 py-1 rounded-full border ${
            b.ok
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-border bg-bg-subtle text-muted'
          }`}
        >
          {b.ok ? (
            <CheckCircle2 className="w-3 h-3" aria-hidden />
          ) : (
            <XCircle className="w-3 h-3" aria-hidden />
          )}
          {b.label}
        </span>
      ))}
      <button
        type="button"
        onClick={() => void probe(true)}
        disabled={probing}
        className="inline-flex items-center gap-1 px-2 py-1 rounded text-muted hover:text-text-secondary hover:bg-bg-hover transition-colors disabled:opacity-50"
        data-testid="office-caps-refresh"
        aria-label={t('office.caps.refresh')}
      >
        <RefreshCw className={`w-3 h-3 ${probing ? 'animate-spin' : ''}`} aria-hidden />
        {t('office.caps.refresh')}
      </button>
    </div>
  );
}
