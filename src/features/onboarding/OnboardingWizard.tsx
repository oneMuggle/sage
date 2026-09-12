/**
 * 首启配置向导（R26）—— Welcome 页无可用端点时展示的三步引导：
 * 协议 → 地址与密钥 → 测试连接并选模型。
 *
 * 背景: 差距分析 D6 指出此前"完全没有首次启动引导"——端点未配置时
 * 只有一条警告条跳设置页，无分步向导、无 provider 预设（Cherry Studio
 * 按 provider 列表一键填 baseUrl）。本组件复用 EndpointsTab 同款的
 * testEndpointConnection，测试通过后一次性写入 endpoints + chatModel 选择。
 */

import { Check, ChevronRight, Loader2, X } from 'lucide-react';
import { useState } from 'react';

import {
  DEFAULT_ENDPOINT,
  type EndpointConfig,
  type EndpointProtocol,
} from '../../entities/setting/types';
import { useI18n } from '../../shared/lib/i18n';
import {
  testEndpointConnection,
  type ConnectionTestResult,
} from '../manage-endpoints/api';
import { useSettings } from '../manage-settings/useSettings';

const PROTOCOLS: { value: EndpointProtocol; labelKey: string; hint: string }[] = [
  { value: 'openai-compatible', labelKey: 'wizard.proto.openai', hint: 'OpenAI / DeepSeek / 月之暗面 / 硅基流动 …' },
  { value: 'anthropic', labelKey: 'wizard.proto.anthropic', hint: 'Claude 系列模型' },
  { value: 'gemini', labelKey: 'wizard.proto.gemini', hint: 'Google AI Studio' },
  { value: 'ollama', labelKey: 'wizard.proto.ollama', hint: '本地 Ollama（无需密钥）' },
];

const MAX_BASEURL_LEN = 300;

export function OnboardingWizard({ onComplete }: { onComplete?: () => void }) {
  const { t } = useI18n();
  const { settings, updateSettings } = useSettings();
  const [step, setStep] = useState(0);
  const [protocol, setProtocol] = useState<EndpointProtocol>('openai-compatible');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [saved, setSaved] = useState(false);

  const needsKey = protocol !== 'ollama';

  const canNextFromCreds =
    baseUrl.trim().length > 0 &&
    baseUrl.trim().length <= MAX_BASEURL_LEN &&
    (!needsKey || apiKey.trim().length > 0);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testEndpointConnection(baseUrl.trim(), apiKey.trim());
      setTestResult(result);
    } catch (error) {
      setTestResult({
        success: false,
        message: error instanceof Error ? error.message : String(error),
        latency: 0,
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = () => {
    const endpoint: EndpointConfig = {
      ...DEFAULT_ENDPOINT,
      id: crypto.randomUUID(),
      name: `${PROTOCOLS.find((p) => p.value === protocol)?.labelKey ?? protocol}`,
      baseUrl: baseUrl.trim(),
      apiKey: apiKey.trim(),
      protocol,
      modelId: selectedModel,
      discoveredModels: testResult?.success ? (testResult.discoveredModels ?? []) : [],
      lastDiscoveredAt: testResult?.success ? Date.now() : null,
    };
    void updateSettings({
      endpoints: [...settings.endpoints, endpoint],
      modelSelections: {
        ...settings.modelSelections,
        chatModel: { endpointId: endpoint.id, modelId: selectedModel || null },
      },
    });
    setSaved(true);
    setStep(3);
  };

  if (saved) {
    return (
      <div
        data-testid="onboarding-wizard"
        className="w-full max-w-xl mx-auto p-5 rounded-radius-md border border-primary/30 bg-surface"
      >
        <div className="flex items-center gap-2 text-primary font-medium">
          <Check className="w-5 h-5" />
          {t('wizard.done.title')}
        </div>
        <p className="text-xs text-text-secondary mt-1">{t('wizard.done.desc')}</p>
        <button
          type="button"
          data-testid="wizard-finish"
          onClick={() => onComplete?.()}
          className="mt-3 px-3 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
        >
          {t('wizard.done.start')}
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="onboarding-wizard"
      className="w-full max-w-xl mx-auto p-5 rounded-radius-md border border-border bg-surface relative"
    >
      <button
        type="button"
        data-testid="wizard-skip"
        onClick={() => onComplete?.()}
        className="absolute top-3 right-3 p-1 rounded hover:bg-bg-hover text-muted"
        title={t('wizard.skip')}
        aria-label={t('wizard.skip')}
      >
        <X className="w-4 h-4" />
      </button>
      <h2 className="text-sm font-semibold text-text">{t('wizard.title')}</h2>
      <p className="text-xs text-text-secondary mt-0.5">{t('wizard.subtitle')}</p>

      {/* 步骤指示 */}
      <div className="flex items-center gap-1 mt-3 text-[11px] text-text-secondary">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`px-1.5 py-0.5 rounded ${step === i ? 'bg-primary/10 text-primary font-medium' : step > i ? 'text-primary' : ''}`}
          >
            {i + 1}. {t(`wizard.step${i + 1}` as Parameters<typeof t>[0])}
          </span>
        ))}
      </div>

      {step === 0 && (
        <div className="mt-3 space-y-2" data-testid="wizard-step-protocol">
          {PROTOCOLS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setProtocol(p.value)}
              className={`w-full text-left px-3 py-2 rounded-radius-sm border transition-colors ${
                protocol === p.value
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:bg-bg-hover'
              }`}
            >
              <div className="text-xs font-medium text-text">{t(p.labelKey as Parameters<typeof t>[0])}</div>
              <div className="text-[11px] text-text-secondary">{p.hint}</div>
            </button>
          ))}
          <button
            type="button"
            data-testid="wizard-next-0"
            onClick={() => setStep(1)}
            className="mt-1 inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
          >
            {t('wizard.next')}
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {step === 1 && (
        <div className="mt-3 space-y-2" data-testid="wizard-step-credentials">
          <label className="block text-xs text-text-secondary">
            {t('wizard.baseurl')}
            <input
              data-testid="wizard-baseurl"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={
                protocol === 'ollama' ? 'http://localhost:11434' : 'https://api.example.com/v1'
              }
              className="mt-1 w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
            />
          </label>
          {needsKey && (
            <label className="block text-xs text-text-secondary">
              {t('wizard.apikey')}
              <input
                data-testid="wizard-apikey"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="mt-1 w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
              />
            </label>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep(0)}
              className="px-3 py-1.5 text-xs rounded-radius-sm border border-border hover:bg-bg-hover"
            >
              {t('wizard.back')}
            </button>
            <button
              type="button"
              data-testid="wizard-next-1"
              disabled={!canNextFromCreds}
              onClick={() => setStep(2)}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            >
              {protocol === 'openai-compatible' ? t('wizard.next') : t('wizard.save_direct')}
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="mt-3 space-y-2" data-testid="wizard-step-test">
          {protocol === 'openai-compatible' ? (
            <>
              <button
                type="button"
                data-testid="wizard-test"
                disabled={testing}
                onClick={() => void handleTest()}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-radius-sm border border-border hover:bg-bg-hover disabled:opacity-50"
              >
                {testing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('wizard.test')}
              </button>
              {testResult && (
                <p
                  className={`text-xs ${testResult.success ? 'text-primary' : 'text-error'}`}
                  data-testid="wizard-test-result"
                >
                  {testResult.message}
                </p>
              )}
              {testResult?.success && (testResult.discoveredModels?.length ?? 0) > 0 && (
                <label className="block text-xs text-text-secondary">
                  {t('wizard.pick_model')}
                  <select
                    data-testid="wizard-model"
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="mt-1 w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
                  >
                    <option value="">{t('wizard.pick_model_hint')}</option>
                    {testResult.discoveredModels!.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          ) : (
            <p className="text-xs text-text-secondary">{t('wizard.skip_test_hint')}</p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="px-3 py-1.5 text-xs rounded-radius-sm border border-border hover:bg-bg-hover"
            >
              {t('wizard.back')}
            </button>
            <button
              type="button"
              data-testid="wizard-save"
              onClick={handleSave}
              className="px-3 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
            >
              {t('wizard.save')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
