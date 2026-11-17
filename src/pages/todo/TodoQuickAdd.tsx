/**
 * TodoQuickAdd — 自然语言快速录入弹窗。
 *
 * 输入如「明天下午3点 交报告 !高 #工作」→ 本地 parseQuickTodo 实时解析
 * → 预览 chips（日期 / 优先级 / 标签）→ 回车或点按创建。
 * 麦克风按钮：MediaRecorder 录音 → 后端 ASR 转写 → 文字追加到输入框。
 */
import { Calendar, Flag, Hash, Loader2, Mic, Square } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { asrClient } from '../../shared/api/asrClient';
import type { CreateTodoInput, TodoPriority } from '../../shared/api/types';
import { Modal } from '../../shared/ui';

import { parseQuickTodo } from './parseQuickTodo';

interface TodoQuickAddProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (input: CreateTodoInput) => Promise<void>;
}

const PRIORITY_LABEL: Record<TodoPriority, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

/** 单段录音上限（毫秒），避免误触产生超长音频。 */
const MAX_RECORDING_MS = 60_000;

function formatDuePreview(dueAt: string): string {
  const d = new Date(dueAt);
  return d.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = String(reader.result ?? '');
      resolve(result.includes(',') ? result.split(',')[1] : '');
    };
    reader.onerror = () => reject(reader.error ?? new Error('读取音频失败'));
    reader.readAsDataURL(blob);
  });
}

export function TodoQuickAdd({ isOpen, onClose, onSubmit }: TodoQuickAddProps) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const parsed = useMemo(() => parseQuickTodo(text), [text]);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const autoStopRef = useRef<number | null>(null);

  const canSubmit = parsed.title.trim().length > 0 && !busy;

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (autoStopRef.current !== null) {
      window.clearTimeout(autoStopRef.current);
      autoStopRef.current = null;
    }
    recorderRef.current = null;
    setRecording(false);
  };

  // 关闭弹窗/卸载时释放麦克风。
  useEffect(() => {
    if (!isOpen) stopStream();
    return () => stopStream();
  }, [isOpen]);

  const handleTranscribe = async () => {
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
    chunksRef.current = [];
    if (blob.size === 0) return;

    setTranscribing(true);
    try {
      const base64 = await blobToBase64(blob);
      const result = await asrClient.transcribe(base64, 'webm', 'zh');
      const recognized = result.text.trim();
      if (recognized) {
        setText((prev) => (prev.trim() ? `${prev.trim()} ${recognized}` : recognized));
      }
    } catch (err) {
      toast.error(`语音识别失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setTranscribing(false);
    }
  };

  const startRecording = async () => {
    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === 'undefined'
    ) {
      toast.error('当前环境不支持录音');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredMime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : '';
      const recorder = preferredMime
        ? new MediaRecorder(stream, { mimeType: preferredMime })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stopStream();
        void handleTranscribe();
      };
      recorderRef.current = recorder;
      streamRef.current = stream;
      recorder.start();
      setRecording(true);
      autoStopRef.current = window.setTimeout(() => {
        recorderRef.current?.stop();
      }, MAX_RECORDING_MS);
    } catch {
      toast.error('无法访问麦克风，请检查系统权限');
    }
  };

  const toggleRecording = () => {
    if (recording) {
      recorderRef.current?.stop();
    } else {
      void startRecording();
    }
  };

  const handleClose = () => {
    stopStream();
    setText('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const input: CreateTodoInput = { title: parsed.title };
    if (parsed.dueAt) input.due_at = parsed.dueAt;
    if (parsed.priority) input.priority = parsed.priority;
    if (parsed.tags.length > 0) input.tags = parsed.tags;

    setBusy(true);
    try {
      await onSubmit(input);
      setText('');
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const hasPreview = Boolean(parsed.dueAt || parsed.priority || parsed.tags.length > 0);

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="快速添加待办"
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            className="px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
            data-testid="quick-add-submit"
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed"
          >
            创建
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        <div className="relative">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void handleSubmit();
              } else if (e.key === 'Escape') {
                handleClose();
              }
            }}
            autoFocus
            placeholder="如：明天下午3点 交报告 !高 #工作"
            aria-label="快速添加待办输入"
            data-testid="quick-add-input"
            className="w-full pl-3 pr-10 py-2 text-sm border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary placeholder:text-text-muted"
          />
          <button
            type="button"
            onClick={toggleRecording}
            disabled={transcribing}
            data-testid="quick-add-mic"
            aria-label={recording ? '停止录音' : '语音输入'}
            title={recording ? '停止录音并识别' : '语音输入（需在设置中配置 ASR 模型）'}
            className={`absolute right-1.5 top-1/2 -translate-y-1/2 w-7 h-7 flex items-center justify-center rounded ${
              recording
                ? 'bg-red-50 dark:bg-red-900/20 text-red-600'
                : 'text-text-muted hover:text-primary hover:bg-bg-hover'
            } disabled:opacity-40`}
          >
            {transcribing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : recording ? (
              <Square className="w-3.5 h-3.5" />
            ) : (
              <Mic className="w-4 h-4" />
            )}
          </button>
        </div>

        <div
          className="flex flex-wrap items-center gap-1.5 min-h-[1.5rem]"
          data-testid="quick-add-preview"
        >
          {parsed.dueAt && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 text-ui-xs rounded-full border border-border text-text-muted">
              <Calendar className="w-3 h-3" />
              {formatDuePreview(parsed.dueAt)}
            </span>
          )}
          {parsed.priority && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 text-ui-xs rounded-full border border-border text-text-muted">
              <Flag className="w-3 h-3" />
              优先级 {PRIORITY_LABEL[parsed.priority]}
            </span>
          )}
          {parsed.tags.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600"
            >
              <Hash className="w-3 h-3" />
              {tag}
            </span>
          ))}
          {!hasPreview && text.trim().length > 0 && (
            <span className="text-ui-xs text-text-muted">未识别到时间/优先级/标签，直接创建</span>
          )}
        </div>

        <p className="text-ui-xs text-text-muted">
          支持：今天 / 明天 / 后天 / 周一 / 1月20日 / 下午3点 / 9点半 · !高 !中 !低 · #标签
        </p>
      </div>
    </Modal>
  );
}
