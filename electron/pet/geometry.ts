/**
 * Pure window geometry for the pet overlay.
 *
 * Adapted from dsh-pet's pointer-target / desktop-geometry ideas (MIT),
 * rewritten in TypeScript for Sage's single-window P0.
 */

import type { PetSize } from './types';

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect extends Point, Size {}

export type WorkArea = Rect;

export const PET_SIZE_WIDTHS: Record<PetSize, number> = {
  mini: 160,
  small: 220,
  medium: 300,
  large: 400,
  huge: 520,
};

/** dsh-pet animation canvas is 640×360 (16:9). */
export const PET_ASPECT = 360 / 640;
/** Extra top space for the speech bubble. */
export const BUBBLE_HEIGHT = 72;

export function petWindowSize(size: PetSize): Size {
  const width = PET_SIZE_WIDTHS[size];
  return { width, height: Math.round(width * PET_ASPECT) + BUBBLE_HEIGHT };
}

export function isPointInRect(point: Point, rect: Rect): boolean {
  return (
    point.x >= rect.x &&
    point.x < rect.x + rect.width &&
    point.y >= rect.y &&
    point.y < rect.y + rect.height
  );
}

/**
 * Interaction hit box inside the window: the central body of the animation,
 * excluding the bubble strip and transparent side margins.
 */
export function petHitBox(bounds: Rect): Rect {
  const marginX = Math.round(bounds.width * 0.22);
  const top = bounds.y + Math.round(bounds.height * 0.28);
  return {
    x: bounds.x + marginX,
    y: top,
    width: bounds.width - marginX * 2,
    height: bounds.y + bounds.height - top,
  };
}

export function clampToWorkArea(point: Point, size: Size, workArea: WorkArea): Point {
  const maxX = workArea.x + Math.max(0, workArea.width - size.width);
  const maxY = workArea.y + Math.max(0, workArea.height - size.height);
  const x = Math.min(Math.max(point.x, workArea.x), maxX);
  const y = Math.min(Math.max(point.y, workArea.y), maxY);
  return { x, y };
}

export function defaultPosition(workArea: WorkArea, size: Size, margin = 24): Point {
  return clampToWorkArea(
    {
      x: workArea.x + workArea.width - size.width - margin,
      y: workArea.y + workArea.height - size.height - margin,
    },
    size,
    workArea,
  );
}
