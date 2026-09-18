// src/features/pet/builtinPacks.ts
//
// 宠物包规范（docs/plans/2026-09-18_desktop-pet-design.md §2.2）。
//
// 渲染层只认 PetPackDescriptor：id + 每状态 → CSS 动画类。内置包以 TS
// 常量声明；P2 导入的 zip 解包校验后生成同型 descriptor——两来源同一
// 渲染路径，无特例。缺失状态回退 idle 动画（可选叠加色调滤镜），保证
// 半套动画的包也不会"冻住"。

import type { PetState } from './petStore';

export interface PetPackDescriptor {
  id: string;
  /** 展示名（内置包直接双语由 UI 层查 i18n；此处存中文兜底） */
  name: string;
  /** 本体形状/配色的 CSS 类（定义于 widgets/pet/pet.css） */
  bodyClass: string;
  /** PetState → 动画 CSS 类；缺省回退 idle */
  animations: Partial<Record<PetState, string>>;
}

const ALL_STATES_ANIMATED = (prefix: string): Record<PetState, string> => ({
  idle: `pet-anim-${prefix}-idle`,
  sleeping: `pet-anim-${prefix}-sleeping`,
  thinking: `pet-anim-${prefix}-thinking`,
  working: `pet-anim-${prefix}-working`,
  reporting: `pet-anim-${prefix}-reporting`,
  celebrate: `pet-anim-${prefix}-celebrate`,
  failed: `pet-anim-${prefix}-failed`,
  attention: `pet-anim-${prefix}-attention`,
});

export const MINT_BLOB: PetPackDescriptor = {
  id: 'mint-blob',
  name: '薄荷团子',
  bodyClass: 'pet-body-mint-blob',
  animations: ALL_STATES_ANIMATED('mint'),
};

export const VIOLET_CAT: PetPackDescriptor = {
  id: 'violet-cat',
  name: '紫罗兰猫',
  bodyClass: 'pet-body-violet-cat',
  animations: ALL_STATES_ANIMATED('violet'),
};

export const BUILTIN_PETS: readonly PetPackDescriptor[] = [MINT_BLOB, VIOLET_CAT];

// P2：导入包在运行时注册（importedPacks store 拉取成功后写入），
// 与内置包共用 getPetPack 解析——两来源同一渲染路径，无特例。
let importedPacks: readonly PetPackDescriptor[] = [];

export function setImportedPacks(packs: readonly PetPackDescriptor[]): void {
  importedPacks = packs;
}

/** 设置页选择器用：内置在前，导入包按 id 序追加。 */
export function listAllPacks(): readonly PetPackDescriptor[] {
  return [...BUILTIN_PETS, ...importedPacks];
}

/** 按 id 取包（内置 → 导入）；未知 id（如 P2 删除了当前选中项）回退内置第一只。 */
export function getPetPack(petId: string): PetPackDescriptor {
  return (
    BUILTIN_PETS.find((pack) => pack.id === petId) ??
    importedPacks.find((pack) => pack.id === petId) ??
    BUILTIN_PETS[0]
  );
}

/** 状态 → 动画类，缺省回退 idle（渲染层唯一的兜底规则）。 */
export function petAnimationClass(pack: PetPackDescriptor, state: PetState): string {
  return pack.animations[state] ?? pack.animations.idle ?? 'pet-anim-fallback';
}
