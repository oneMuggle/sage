// src/shared/ui/Lightbox/Lightbox.tsx
//
// P1 (UI 优化方案 2026-09-13): 统一图片查看器 —— 缩放（滚轮/按钮）、
// 拖拽平移、双击/按钮重置、ESC/点背景关闭。替代此前散落的简易
// bg-black/70 遮罩（MediaAttachment）。portal 到 body，不受父级
// overflow/z-index 影响。

import { RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const MIN_SCALE = 0.2;
const MAX_SCALE = 8;
const WHEEL_STEP = 1.15;

const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

export interface LightboxProps {
  src: string;
  alt?: string;
  onClose: () => void;
}

export function Lightbox({ src, alt, onClose }: LightboxProps) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ px: number; py: number; bx: number; by: number } | null>(null);

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const zoomBy = (factor: number) => setScale((s) => clampScale(s * factor));
  const reset = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  const onPointerDown = (e: React.PointerEvent<HTMLImageElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { px: e.clientX, py: e.clientY, bx: offset.x, by: offset.y };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLImageElement>) => {
    const d = dragRef.current;
    if (!d) return;
    setOffset({ x: d.bx + (e.clientX - d.px), y: d.by + (e.clientY - d.py) });
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };

  return createPortal(
    <div
      data-testid="lightbox"
      className="fixed inset-0 z-[70] bg-black/85 flex flex-col"
      onClick={onClose}
      onWheel={(e) => zoomBy(e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP)}
    >
      {/* 工具栏 — stopPropagation 避免点按钮误关 */}
      <div
        className="flex items-center justify-center gap-1 p-2 bg-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <LbButton label="缩小" onClick={() => zoomBy(1 / WHEEL_STEP)}>
          <ZoomOut className="w-4 h-4" />
        </LbButton>
        <span className="text-xs text-gray-300 w-10 text-center tabular-nums" data-testid="lightbox-zoom">
          {Math.round(scale * 100)}%
        </span>
        <LbButton label="放大" onClick={() => zoomBy(WHEEL_STEP)}>
          <ZoomIn className="w-4 h-4" />
        </LbButton>
        <LbButton label="重置" onClick={reset}>
          <RotateCcw className="w-4 h-4" />
        </LbButton>
        <LbButton label="关闭" onClick={onClose}>
          <X className="w-4 h-4" />
        </LbButton>
      </div>
      <div className="flex-1 flex items-center justify-center overflow-hidden p-4">
        <img
          src={src}
          alt={alt ?? ''}
          draggable={false}
          data-testid="lightbox-image"
          className="max-w-[92vw] max-h-[86vh] object-contain select-none cursor-grab active:cursor-grabbing"
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={reset}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      </div>
    </div>,
    document.body,
  );
}

function LbButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="p-1.5 rounded text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
    >
      {children}
    </button>
  );
}
