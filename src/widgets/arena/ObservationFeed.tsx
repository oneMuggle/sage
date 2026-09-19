/**
 * ObservationFeed — 被动模型观测流 (2026-09-19)
 *
 * 展示 ModelObservationService 的最近模型判定；attach/detach 由用户显式
 * 触发。观测是纯被动的：只读 sage 自管浏览器页面的 CDP Network 事件帧。
 */
import { useEffect, useRef, useState } from 'react';

import {
  attachObservation,
  detachObservation,
  listObservations,
  type ModelVerdict,
} from '../../entities/arena';

interface ObservationFeedProps {
  onError: (message: string) => void;
  onStatus: (message: string | null) => void;
}

export function ObservationFeed({ onError, onStatus }: ObservationFeedProps) {
  const [attached, setAttached] = useState(false);
  const [verdicts, setVerdicts] = useState<ModelVerdict[]>([]);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    let disposed = false;
    const tick = () => {
      void (async () => {
        try {
          const res = await listObservations(20);
          if (disposed) return;
          setAttached(res.attached);
          setVerdicts(res.verdicts);
        } catch {
          // 后端未启用（403）或不可达：静默保持空态
        }
      })();
    };
    tick();
    pollRef.current = window.setInterval(tick, 5000);
    return () => {
      disposed = true;
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, []);

  async function handleToggle(): Promise<void> {
    setBusy(true);
    onError('');
    try {
      if (attached) {
        await detachObservation();
        onStatus('观测已停止');
        setAttached(false);
        setVerdicts([]);
      } else {
        await attachObservation();
        onStatus('观测已启动（监听当前浏览器页面的网络事件）');
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="border border-border rounded p-3 space-y-2"
      data-testid="observation-feed"
      aria-label="模型观测"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-medium">模型观测（被动）</h2>
        <button
          type="button"
          disabled={busy}
          data-testid="observation-toggle"
          onClick={() => void handleToggle()}
          className={`text-xs rounded px-3 py-1.5 disabled:opacity-50 ${
            attached
              ? 'border border-border hover:bg-bg-hover'
              : 'bg-primary text-white hover:opacity-90'
          }`}
        >
          {attached ? '停止观测' : '启动观测'}
        </button>
      </header>
      <p className="text-xs text-text-muted">
        只读 Sage 自管浏览器页面的网络事件，推断当前会话真实模型；不注入、不修改任何请求。
      </p>
      {verdicts.length === 0 ? (
        <p className="text-xs text-text-muted" data-testid="observation-empty" role="status">
          {attached ? '已连接，等待浏览器产生模型判定…' : '未启动。先在主界面启动浏览器会话后点击「启动观测」。'}
        </p>
      ) : (
        <ul className="space-y-1" data-testid="observation-list">
          {verdicts.map((verdict, index) => (
            <li
              key={`${verdict.observed_at ?? index}-${index}`}
              className="flex items-center gap-2 text-xs border-t border-border pt-1"
            >
              <span className="font-mono" data-testid="observation-model">
                {verdict.modelId ?? verdict.family ?? '未知'}
              </span>
              {verdict.family && verdict.modelId && (
                <span className="text-text-muted">({verdict.family})</span>
              )}
              <span className="text-text-muted">
                置信度 {(verdict.confidence * 100).toFixed(0)}%
              </span>
              {verdict.source && <span className="text-text-muted">来源 {verdict.source}</span>}
              {verdict.observed_at && <span className="ml-auto text-text-muted">{verdict.observed_at}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
