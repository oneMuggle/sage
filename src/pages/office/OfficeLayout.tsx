/**
 * OfficeLayout — 文档工作台的三栏布局壳（left / center / right?）。
 *
 * 只负责网格排布，不关心插槽内容：P1 用 left（文档库）+ center（文档画布）
 * 两栏，P2 的 AI 侧栏会作为可选的 right 栏接入。右栏缺席时网格只声明两列，
 * 不会把 left / center 挤进隐式的第二行。
 */

import type { ReactNode } from 'react';

interface OfficeLayoutProps {
  left: ReactNode;
  center: ReactNode;
  right?: ReactNode;
}

export function OfficeLayout({ left, center, right }: OfficeLayoutProps) {
  const gridCols = right
    ? 'lg:grid-cols-[minmax(200px,260px)_minmax(0,1fr)_320px]'
    : 'lg:grid-cols-[minmax(200px,260px)_minmax(0,1fr)]';

  return (
    <div className={`flex-1 grid gap-4 ${gridCols}`} data-testid="office-layout">
      <div data-testid="office-layout-left" className="flex flex-col gap-4">
        {left}
      </div>
      <div data-testid="office-layout-center" className="flex flex-col gap-4">
        {center}
      </div>
      {right && (
        <div
          data-testid="office-layout-right"
          className="hidden lg:flex lg:flex-col gap-4 w-[320px]"
        >
          {right}
        </div>
      )}
    </div>
  );
}
