/**
 * RegisterAssist — 单账号注册向导 (2026-09-19)
 *
 * 驱动后端 ArenaRegistrationService 的状态机：
 *   start → awaiting_signup（人工验证码）→ verification_ready（用户点开链接）
 *   → awaiting_password（代填或手动输入）→ completed（入账号池）
 *
 * 明确提示：人机验证必须由用户本人在打开的浏览器中完成；本向导只做
 * 填表/导航等辅助动作。
 */
import { useEffect, useRef, useState } from 'react';

import {
  cancelRegistration,
  getRegistration,
  openVerification,
  setRegistrationPassword,
  startRegistration,
  type RegistrationStatus,
} from '../../entities/arena';

interface RegisterAssistProps {
  onCompleted: () => void;
  onError: (message: string) => void;
  onStatus: (message: string | null) => void;
}

const STATE_STEPS: RegistrationStatus['state'][] = [
  'awaiting_signup',
  'awaiting_verification',
  'verification_ready',
  'awaiting_password',
];

const STATE_LABELS: Record<RegistrationStatus['state'], string> = {
  awaiting_signup: '填写注册表单（人工验证码）',
  awaiting_verification: '等待验证邮件',
  verification_ready: '验证邮件已到',
  awaiting_password: '设置密码',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  expired: '已超时',
};

const TERMINAL: RegistrationStatus['state'][] = ['completed', 'failed', 'cancelled', 'expired'];

export function RegisterAssist({ onCompleted, onError, onStatus }: RegisterAssistProps) {
  const [status, setStatus] = useState<RegistrationStatus | null>(null);
  const [password, setPassword] = useState('');
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<number | null>(null);

  // 挂载时恢复进行中的注册（页面切换 / 后端已有活跃会话）
  useEffect(() => {
    void (async () => {
      try {
        const existing = await getRegistration();
        if (existing && existing.state) setStatus(existing);
      } catch {
        // 404：无进行中注册 —— 保持引导态
      }
    })();
  }, []);

  // 有活跃注册时轮询状态（5s），终态自动停止
  useEffect(() => {
    const active = status !== null && !TERMINAL.includes(status.state);
    if (!active) {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const next = await getRegistration();
          if (next && next.state) setStatus(next);
        } catch {
          // 瞬时错误：保留当前展示，下一轮轮询重试
        }
      })();
    }, 5000);
    timerRef.current = id;
    return () => {
      window.clearInterval(id);
    };
  }, [status]);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
    },
    [],
  );

  async function handleStart(): Promise<void> {
    setBusy(true);
    onError('');
    onStatus(null);
    try {
      const next = await startRegistration();
      setStatus(next);
      onStatus(`已创建临时邮箱 ${next.email}，注册页已在浏览器中打开`);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runStep(action: () => Promise<unknown>, okMessage: string): Promise<void> {
    setBusy(true);
    onError('');
    try {
      await action();
      onStatus(okMessage);
      if (okMessage.includes('入池')) {
        setStatus(null);
        onCompleted();
      } else {
        const next = await getRegistration();
        setStatus(next);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const terminal = status !== null && TERMINAL.includes(status.state);
  const stepIndex = status ? STATE_STEPS.indexOf(status.state) : -1;

  return (
    <section
      className="border border-border rounded p-3 space-y-3"
      data-testid="register-assist"
      aria-label="注册新账号"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-medium">注册新账号（单账号 · 人工验证码）</h2>
        {status === null || terminal ? (
          <button
            type="button"
            disabled={busy}
            data-testid="register-start"
            onClick={() => void handleStart()}
            className="text-xs rounded bg-primary text-white px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            {busy ? '启动中…' : '开始注册'}
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            data-testid="register-cancel"
            onClick={() => void runStep(cancelRegistration, '已取消')}
            className="text-xs rounded border border-border px-3 py-1.5 hover:bg-bg-hover disabled:opacity-50"
          >
            取消注册
          </button>
        )}
      </header>

      {status === null && (
        <p className="text-xs text-text-muted">
          流程：创建临时邮箱 → 打开注册页（自动填邮箱）→
          <strong className="text-warning"> 你本人完成人机验证</strong> →
          点击验证链接 → 设置密码（可代填）→ 入账号池。全程单账号，无批量模式。
        </p>
      )}

      {status !== null && (
        <div className="space-y-2 text-xs" data-testid="register-status">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{status.email}</span>
            <span
              className={`rounded px-1.5 py-0.5 ${
                status.state === 'completed'
                  ? 'bg-success/15 text-success'
                  : status.state === 'failed'
                    ? 'bg-error/15 text-error'
                    : 'bg-primary/15 text-primary'
              }`}
              data-testid="register-state"
            >
              {STATE_LABELS[status.state]}
            </span>
            <span className="text-text-muted">剩 {Math.ceil(status.expires_in_sec / 60)} 分钟</span>
          </div>

          {STATE_STEPS.map((step, index) => (
            <div
              key={step}
              className={`flex items-center gap-2 ${index <= stepIndex ? 'text-text' : 'text-text-muted'}`}
            >
              <span aria-hidden="true">{index < stepIndex ? '✓' : index === stepIndex ? '➤' : '·'}</span>
              {STATE_LABELS[step]}
            </div>
          ))}

          {status.captcha_present && (
            <p className="rounded bg-warning/15 text-warning p-2" data-testid="captcha-hint">
              检测到人机验证 —— 请在打开的浏览器窗口中手动完成，本工具不会代过验证。
            </p>
          )}
          {!status.email_filled && status.state === 'awaiting_signup' && (
            <p className="text-text-muted">自动填邮箱未命中表单，请在浏览器中手动填写注册邮箱。</p>
          )}
          {status.manual_hint && <p className="text-text-muted">{status.manual_hint}</p>}
          {status.error && (
            <p className="rounded bg-error/10 text-error p-2" data-testid="register-error-box">
              {status.error}
            </p>
          )}

          {status.state === 'verification_ready' && (
            <button
              type="button"
              disabled={busy}
              data-testid="register-open-verify"
              onClick={() =>
                void runStep(openVerification, '已在浏览器中打开验证链接')
              }
              className="text-xs rounded bg-accent text-white px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
            >
              在浏览器中打开验证链接
            </button>
          )}

          {status.state === 'awaiting_password' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="密码（≥8 位，含大小写字母/数字/符号）"
                  data-testid="register-password"
                  className="flex-1 rounded border border-border bg-bg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <button
                  type="button"
                  disabled={busy || password.length === 0}
                  data-testid="register-submit-password"
                  onClick={() =>
                    void runStep(
                      () => setRegistrationPassword(password, manual),
                      '密码已设置，账号已入池',
                    )
                  }
                  className="text-xs rounded bg-primary text-white px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
                >
                  设置并入池
                </button>
              </div>
              <label className="flex items-center gap-1.5 text-text-muted">
                <input
                  type="checkbox"
                  checked={manual}
                  onChange={(e) => setManual(e.target.checked)}
                  data-testid="register-manual"
                />
                我已在浏览器中手动输入相同密码（跳过代填）
              </label>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
