// W2: buildForkFamily —— 会话分叉家族树纯函数。
// 覆盖：根回溯、后代收集与排序、环兜底、祖先缺失兜底、非家族会话隔离。

import { describe, expect, it } from 'vitest';

import type { Session } from '../../../shared/api/types';
import { buildForkFamily } from '../forkTree';

function sess(id: string, forkRoot: string | null, createdAt: number): Session {
  return {
    id,
    title: `会话-${id}`,
    created_at: createdAt,
    updated_at: createdAt,
    last_message_at: null,
    message_count: 1,
    is_pinned: false,
    fork_root: forkRoot,
  };
}

const T0 = 1700000000000;

describe('buildForkFamily', () => {
  it('非分叉且无后代 → 仅自身', () => {
    const sessions = [sess('a', null, T0), sess('b', null, T0 + 1)];
    const family = buildForkFamily(sessions, 'a');
    expect(family.map((n) => n.session.id)).toEqual(['a']);
    expect(family[0].depth).toBe(0);
  });

  it('两代分叉：根在前，后代按创建时间排序', () => {
    // root <- b(T0+2) <- c(T0+1)：c 是 b 的子但创建更早，仍按时间排子层
    const sessions = [
      sess('root', null, T0),
      sess('b', 'root', T0 + 2),
      sess('c', 'b', T0 + 1),
      sess('d', null, T0 + 3), // 无关会话
    ];
    const family = buildForkFamily(sessions, 'c');
    expect(family.map((n) => n.session.id)).toEqual(['root', 'b', 'c']);
    expect(family.map((n) => n.depth)).toEqual([0, 1, 2]);
  });

  it('兄弟分支同层：按创建时间升序', () => {
    const sessions = [
      sess('root', null, T0),
      sess('late', 'root', T0 + 5),
      sess('early', 'root', T0 + 1),
      sess('me', 'root', T0 + 3),
    ];
    const family = buildForkFamily(sessions, 'me');
    expect(family.map((n) => n.session.id)).toEqual(['root', 'early', 'me', 'late']);
    expect(family.filter((n) => n.depth === 1)).toHaveLength(3);
  });

  it('祖先缺失：以最深可达祖先为根', () => {
    // me 的父 p 不在列表里，但祖父 root 在 —— p 不可达，family 从 me 起算不到 root?
    // 语义：p 缺失导致向上链断在 me（me.fork_root 指向不存在的 p）。
    const sessions = [sess('p', 'root', T0), sess('me', 'p', T0 + 1)];
    const family = buildForkFamily(sessions, 'me');
    // me 向上找不到 p（p 存在但 root 不在集合）—— p 在集合中，可继续走到 root?
    // root 不在集合，链断于 p → 根为 p
    expect(family.map((n) => n.session.id)).toEqual(['p', 'me']);
    expect(family[0].depth).toBe(0);
  });

  it('fork_root 成环：不死循环，从当前会话截断', () => {
    const sessions = [
      sess('a', 'b', T0), // 环：a->b->a
      sess('b', 'a', T0 + 1),
      sess('me', 'a', T0 + 2),
    ];
    const family = buildForkFamily(sessions, 'me');
    // me 向上：a → b → (b->a 已访问) 根=b；下行：b 的子 a、a 的子 me
    expect(family.map((n) => n.session.id)).toEqual(['b', 'a', 'me']);
  });
});
