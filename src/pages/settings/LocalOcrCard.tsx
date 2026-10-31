/**
 * 设置页「本地 OCR」卡片：状态展示 + 语言/优先策略配置。
 *
 * 数据源：
 * - `GET /api/v1/ocr/capabilities`（引擎/模型可用性）
 * - preferences KV `ocr_config`（JSON：enabled/engine/lang/prefer_local_for_images）
 */

import { useEffect, useState } from 'react';

import { ocrApi, type OcrCapabilities } from '../../shared/api/ocrApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n } from '../../shared/lib/i18n';

export interface LocalOcrConfig {
  enabled: boolean;
  engine: 'auto' | 'rapidocr' | 'tesseract';
  lang: 'auto' | 'ch' | 'en';
  prefer_local_for_images: boolean;
  max_side: number;
  use_cls: boolean;
}

const DEFAULT_CONFIG: LocalOcrConfig = {
  enabled: true,
  engine: 'auto',
  lang: 'auto',
  prefer_local_for_images: false,
  max_side: 1280,
  use_cls: false,
};

//: 内置测试图（420×120，文字 SAGE OCR 123）
const TEST_IMAGE =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAaQAAAB4CAIAAAAypRGCAAAUN0lEQVR42u2df1SMWfzHp6kI/URkKBEix5JdUkjbUrLJj7DLdqwcJ9avtljZ3Zb2LCtse1rZXVRrsQinrUQ/yCkqkW2R2uh0UtFIZaZUo+nHzPeP53vu937nx9NTMg29X3/dZu79zNN95nnP537u596rI5fLeQAA8K7DRxcAACB2AAAAsQMAAIgdAABA7AAAAGIHAAAQOwAAgNgBAADEDgAAsQMAAIgdAABA7AAAAGIHAAAQOwAAgNgBAADEDgAAIHYAAACxAwBA7AAAAGIHAAAQOwAAgNgBAADEDgAAIHYAAACxAwAAiB0AAEDsAAAQOwAAgNgBAADEDgAAIHYAAACxAwAAiB0AAEDsAAAAYgcAABA7AADEDgAAIHYAAACxAwAAiB0AAEDsAAAAYgcAABA7AACA2AEAAMQOAACxAwAAiB0AAEDsAAAAYgcAABA7AACA2AEAQHegp/mPzMrKiomJyc7OrqysrK+vNzc3Hz58+AcffODt7e3s7Kynp9cjHSGVStPT0xMSEu7evVtVVfX8+XNjY2NLS0sbG5ulS5d6eXn169dP227e/fv3Y2NjMzIyhEKhUCjs16+fQCAYNWrUwoULFy9ebG5u3jWzIpEoMTExMTGxpKREKBQ2NDRYWlpaWVnNnz9/1apVAoHgnfn2y+Xy69evnzhxorCwsKKioq6uztzcfMKECe7u7r6+vgMHDuRi5Pbt2+fOncvOzn769KlYLLa2th47dqytre3atWvHjx8PidGu+60xHj16tGTJEpaLsba2jomJ4W6wsrKSz/8/5/T06dNduKqWlpaff/7ZzMyM5cKMjIwOHDjQ2tqqzoiBgUGnut3CwuJ1evKff/6ZMWMGi31dXd3NmzeLxeJOmRWLxf7+/vr6+moHAnz+unXrRCJRF/rBwMDAxsbG2dl55cqVISEh+fn53fKlam1t/euvvyZPnsx8iqenJ8eGN2/enDBhgrqrNTY2Pnz4MLuFW7duOTg4sNyCtWvXVlRUyIF2oDmxi4yM5Oi1zZs3j+NTGh4eTjdcuHBhZ6/q/v37Y8aM4ahQU6ZMefLkSY+L3bfffktLPAvm5ubXr1/naDY1NZWjMzh06NBbt269fj+4uLjcvXu3a51QXV19/vz5DRs2DB8+nLbJUex27dqlq6tLN9TR0VG+wm3btqls3t7evnPnTuUmyq+Ym5sXFhZCaHqR2CUlJdHP57Bhw3bs2BEVFZWcnHzmzJk9e/bMmDGD/qJMnjy5ra2tQ7MK3k2fPn1YnA5lMjIyTExMaAtWVlZffvllZGTk5cuXY2Njw8PDP/74Y1qjR44cKZFIekrsZDLZpk2baDuGhoarV68+cuTI5cuXL1y4cPDgQWdnZ7on+/Xrl5qa2qHl8+fP9+nTh35onZyc9u3bFxMTk5ycHB0dvX79etr5HTBgwOPHj1+/HwwMDC5evNjZfigqKlKpTVzETiaTbdy4kb4Re/fu/e+//6RSqVAoTE5OXrlyJW3w7Nmzyka+++472uv39/fPyckRi8VSqbSgoCAiImLQoEGkwvjx46VSKbSmV4hdc3OztbU1ufc7dux49eqVSidr7ty5TJ2jR492aLasrIypPHHiRC8vL6YcHR3N3aejn0wrK6u4uDh1H0RGKz/++CO7R+Pq6lrGAXUeIjv79u2jn0M/P7+XL18qV7t37x4Z1jGC8vDhQxaz6enp9E/RjBkzCgoKlKtJJJKvvvqKcYjWrFnD3g8KoiOTyWpqagoKClJSUtatWzdgwABajktKSjrVDwUFBerUs0OxKyoqIp++fPny+vp65TrHjx+nQyvK4QuRSDRu3Dgej+fl5VVZWalsoaamZuTIkcRIVFQUtKZXiF18fDy568uXL+/wefbz8+Nidv/+/YzNoKCg6OhoMgTm0lYikdjZ2ZGrcnZ2VqkadFxv69atK1as6DBWxT1m1FkKCgr69u1LrvnIkSMslaVS6bx580hlR0fH9vZ2dXE6S0tLUtPX11ddTXI358yZ09zc/Dr9UF9fT3vl3t7eneoKkUh05P9D9ItL/2dmZhoaGvr7+7PUWbZsGbm8pKQk5QrFxcW7du2SyWTqLFy5coVY8PDwgNb0CrGjRw1paWndZXbq1KlkereqqorxTXR1dZ8/f95h2x07dpBLmjZtWmNjI5dPZFEBDYidi4sL7R13WL+hoYEW9GPHjqmstmHDBjroya50xE17/X6oqqoi4TYDA4OGhobX6ZzBgwd3qv+Li4tZ/gvGO+4wctfht6V///6MhdGjR0NreoXYkTEmj8fjokQcv6yMwcGDBzPPp6OjI/PKr7/+yt62vr7eyMiIhPm6JX78psUuPz+/w7ihMmlpaaTVpEmTVI62yJUbGxsLhUJN9sMXX3xBLi89PV2TYtchra2tJFa7ZMmSrhkhwYQhQ4ZAa3ocTSQV0wF+IlKvSUxMDFNYsGAB49MRSSVvqSMyMrKhoYEpb968mXZ/tJbffvuNlIODgzkm/X300UfEH3zw4EFmZqZChaNHjzY3NzPl7du3Dxs2TJP/lL29PSlXVVVpVwKqnh4Jur148aJrRioqKpgC9xl/8ObQhNjRsxMXL17sFpvnzp0jIy+mQMQuKyvr6dOnLG3PnDlDyuvXr38r7lNCQgIZ8S1fvpx7w88//1zZiPJvBpMUpuF/asiQIXRSt7b1eUtLC1NQmLLnyOPHj8ViMVNmSegD75TYeXh4kHJYWFhcXNxrGiwoKCgsLOTxePr6+m5ubsyLdnZ2NjY2TJr0hQsX1LV9+fLl/fv3mbKDgwMzp6bllJeXP3v2jDhrnXr2lixZQrI0cnJy6LfEYjHTjTweb/bs2QoJaxqAnlQdO3asVvV5e3s76fOuObwHDhwgeTz0gB28y2I3d+5cd3d3piyTyZYtWxYQEEAGkq/j1s2ZM8fY2Ji8zmUkm52d3d7ezpSdnJzeipt08+ZNejqlU21NTEyIjuTl5dEOVFZWllwuJ+kmmv+/8vLySNnW1lar+jwnJ6etrY0pT58+vbNCGRIScuTIEebPFStWvP/++9CaXiF2PB7v2LFjZE5AJpOFh4dbWVl9/fXXQqGwC9aIlpExrILY5ebmlpaWqmz74MEDUu7sl7inKCkpIWU6gY4jU6ZMIUNFeoBP3Doej6f5pzE1NZUMq21tbeksXG2AjreQ0QM7crm8pKTk8OHDU6ZM+f7778mwhs7aA+++2FlZWV27do0eKNXV1YWGhlpbW69evfru3budcgfIw+/p6Um/NWvWLJLlT7w/Behg84gRI7r9P7106ZIOK5MmTeqsTRL66dqQysLCgpRFIpHKsobHsNnZ2T4+PjKZjPkzNDRUq54KiURCFMrJyYnOQ1SJm5ubjY2NkZHR2LFjt2zZwgzPTUxMdu/enZCQoIVbSEDs3izTpk27c+eOgjy1traeOnVq6tSpH3744bVr1zo1hrW3tx89ejT9lp6eHvH11I1kabFjX/yvPdCq1IVgOd2ENkV3hamp6Rv9F2Qy2bNnz3Jzc8+cOePq6jpr1qza2lrmLRcXl8WLF2tVh0dGRpLLCwgI6LB+UVFRaWlpU1MTeWXQoEFpaWkhISEsuyqAd1bsGK8kMTExOzubTu5nyMjImDt3rpubG5k9UDdSIGJH57gTyK4q+fn5RUVFyhXq6+tJ2dDQUOWnNDU1sbhmmg82009RF9wEktrK4/EaGxtJ+eXLlyrrvAkPV1dXVyAQODg4fPbZZ+np6XTkITExUaseidra2j179pDxNfs+Pep48eLF9OnT582bl5ubC5XREnpg8zgnJ6crV67k5+eHhYWdPXu2tbWVvHX16lVHR8dTp055e3urbHvr1i2Su6RS7Nzd3fv37y+RSBgfMCQkRKECCR0qPPndhbOzM50Tpwy95Isj9CRMF66ZnguiPbg33RUd/vJt2bIlKCiI4w4uGiMgIIC4db/88ovC5igqKS0tbWhoEIvFDx8+zMvLi42NZTawSktLy8zMjIqK8vHxgdb0PD2b01xZWRkUFEQ/dTweT0dH5+TJkyrrb926lanz3nvvqbNJhHLcuHHK727bto2OHKm0wP7kb9iwQcMrKLZv397hNbNAb5SSl5ensiuYmdluXEnC5/MNKGiJ79u3b3x8PJddbTS/giI2NpYeJXTZTnJyMp1eGhsbiwUMvWIFBQsCgSA0NLS8vDwoKIj8hMrl8sDAQDoqT+I+JIGuuLh4mBpSU1NJHXqFIwmmkPKTJ0/UjfuqlJg4cWJP9RK9Za66a2aBbkKbek2z7CxYsOAVRXNzMwnXSqXSFy9ecPGYNExxcbGvry9TtrCwOHr0aJdNzZ8/PzMzk8yABQYGvnr1Cq5VL4rZqcPMzCw0NDQ7O5sMsmpra5Vn6G7cuEHyPJubm6vUQPtlytMUdBYxneel4FoOVaIHI830gjZl+e4Q0sTIyMjKyoq8Tqe2dWpCvGuEh4cT/y4oKEj5x6xnaWho8Pb2ZuKYzNiiy/vaM4wYMYJ8h8vLyyMjIyE3ELv/xcHBgf5C3LhxQ6FCh4telVFuMnv2bDoC+FbcJLLHAY/Hu337dqfaPn/+nEQ5p0+fTgfIZs6c2WWzXcDGxoaMx2tra4ODg7Wnh1taWpYuXUpWdOzdu1d5Dq0L0Al6d+7cgdz06pgdS/DFxMREYRcK8lZAQAC7kYiICPIP5uTkKLxLnDs+n19eXs7xwkhqruZjdnK5nFkJx+O8hxXh0KFDpCuCg4PVmeXz+So3oezeXU+amppIzhqfz//333+1IWYnk8k+/fRT0ks+Pj7deONIXqS9vT2iZr06ZqcM0ZT6+no6KezatWtkjqzDtKxFixaxOHdkGlcmk5FdP7Uccs3t7e2nT5/m3vDkyZOkrLyDwNKlS0lX0DXfEP379w8LCyOfuGnTJrJerQd/7Ddu3Ei+JK6urlFRUd1on8SIuz0qCt56z44s4eLz+fR22CRybG5uzmUij6x/EggEChtSVlZWkgDcgAEDODp3PevZlZaWkhHokCFDVG4mzj63OGvWLOUKZWVlZKLAzMyspqZGA/vZubq6kqs6fvx4D3p2MpnMz8+PDnFw3MaVIy0tLeSbZmdnB9/q3ffsLl++7OfnR5bfsyCVSklS8ZgxY8hGeC0tLWSvFC8vLy4TecT7EwqFCvu4CQQCcqhKU1PTunXr6Fw/7WTUqFFk5W91dTW907I6RCIRnbNCsnZoRo4cSZJmxWLxli1buLha9+7d68I8CSEiIoLc2aCgoLq6up76mV+/fv2xY8eYL4lJSUlxfnw+SUpKog/HYKGyspJLD+Tl5ZGv1luNM+9nd88KuT+9cd4RP3nyhJRtbW21qs9zcnLa2tqY8vTp0zsrlCEhIUeOHGH+XLFixfvvvw+t6RViV1pampaWRh7UYcOGRURE1NbWqjQ6d+5cphAQECCRSDo0/vz5c1NTUyJSCoeq/PLLL6QcGBjY4S00NDQcPnyY48d4fHx8+PDhhAsXLnCtPzk5GVPTVq1aRV45ceIE95P5zp8/z2nMmHEzn19XV6cyoUfdoKCgIJwUUlZWJpVK6+vrExIS6DndPn36qDw8iqPYkdz0adOm7d69u66uTryiubm5rq5u06ZNRK+HDh2qsAIEC72/fn5+AQEByp2ZkpJCRHDkyJEqr00mk9HnSP/zzz/c+2GNGjWK7IiJRCJ1Xwb57NLi3bt3k1f++OMPdf81Ozs7kjawsbFRwwJPzZkzh1xeZmamJsUO9LKkYrFYPHnyZPrxMzY2Xr169ZEjRy5fvhwbGxseHk7vCcnj8VxdXTscKSgkuTDs27ePfuvKlSscL+/WrVv0Gvz6+vq6urp0Ls+oUaPU/TouLi6xHGB3UZV3NEZHR9MzOn/++WflUS09H2Jvb8/xpi5fvpzeQTAoKCg6Ojo1NTU5OTk6Onr9+vX0S2Rqaqry9IWujGgqlbrVfDkyMjJ69WoV/bWwsFB31iR3sZPL5Q8fPqSlU/kcQnVf+7a2Nnrui8fjTZ48ef/+/SkpKcnJyUePHvX19aV7hs/nX758GVrTK8ROLpfLZLLAwEDlR1Qlbm5uCo9ch2Inl8vpRS38+fPnO3zU3717R09x6ejoqFy9IRKJ6H9qY2Oj7lJrampMTU2V/9jU1FT5/B6JRLJ06VLlp8XGxkan1quVlZXRMysqbW1t1W23o4HYyeXykpIS+jxMlrORuYudXC4/c+aM8p8eOXIk+2Vfu3aNlvJ2OTg4qLtNoDViJ5fLb926tWHDBpUb3/v5+f3888/S6fTOih3LwFs5daXSGN8+ffqwtGU5J4sWLeqU2Mnl8o0bN3Io3xu8a2pqHE9Nnz7d3t5eXcxBjdi3tLSq9X1NTUxcXNzGjRsrVqxYtGjRypUrt2zZ8vfff3M87Im72DE8ffpU+dexs7O7c+cOS/OXL18GBQUpx3kGBgbBwcEqh5/Nzc1bt25VblFRUVFXVxe60yvFTkZtbW18fPyePXs+//zzzz77bO3atSEhIYmJiV1YKqQVsbGxISEh69evX7Zs2fr160NCQvbs2RMfH9+pILRm+Pfff318fDw9PVeuXBkREcG+A7d60AjhJSUlxcTE7Ny5c+3atcuXL1+zZs3u3bvj4+NfvHihVf1w9+7d7du3+/r6enl5rV+/PjIysgv7FbEQiUSSk5Pj4+N37dq1YcOGpUuX+vr6bt68+eLFi6zHqgNtQ0eu2USnBw8exMXFZWZmCoVCoVAokUgGDRpkaWk5e/bshQsXcncAu526urqkpKTExMRHjx5VVVXV1taampoOHThw9erSbm5uHh4fC3nnaQGFh4YULF9LT058+ffrs2TMDAwOBQGBjY7No0aLFixcrjL65U1ZWFhcXl5ycXFFRIRQKZTKZQCCwtLR0c3P75JNP6PXtoKmpKSEhISEhoaysrLKysrq62sjISCAQODk5eXl5LViwoMPRMdAYmhY7AADoEfjoAgAAxA4AACB2AAAAsQMAAIgdAABA7AAAAGIHAAAQOwAAgNgBACB2AAAAsQMAAIgdAABA7AAAAGIHAAAQOwAAgNgBAADEDgAAIHYAAIgdAABA7AAAAGIHAAAQOwAAgNgBAADEDgAAIHYAAACxAwAAiB0AAGIHAAAQOwAAgNgBAADEDgAAIHYAAACxAwAAiB0AAEDsAAAAYgcA6JX8Dy4qSbyI3wwKAAAAAElFTkSuQmCC';

function parseConfig(raw: string | null): LocalOcrConfig {
  if (!raw) return DEFAULT_CONFIG;
  try {
    const parsed = JSON.parse(raw) as Partial<LocalOcrConfig>;
    return {
      enabled: parsed.enabled ?? DEFAULT_CONFIG.enabled,
      engine: parsed.engine ?? DEFAULT_CONFIG.engine,
      lang: parsed.lang ?? DEFAULT_CONFIG.lang,
      prefer_local_for_images:
        parsed.prefer_local_for_images ?? DEFAULT_CONFIG.prefer_local_for_images,
      max_side: parsed.max_side ?? DEFAULT_CONFIG.max_side,
      use_cls: parsed.use_cls ?? DEFAULT_CONFIG.use_cls,
    };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function LocalOcrCard() {
  const { t } = useI18n();
  const [caps, setCaps] = useState<OcrCapabilities | null>(null);
  const [config, setConfig] = useState<LocalOcrConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      ocrApi.capabilities().catch(() => null),
      settingsClient.getPreference('ocr_config').catch(() => null),
    ]).then(([nextCaps, rawConfig]) => {
      if (cancelled) return;
      setCaps(nextCaps);
      setConfig(parseConfig(rawConfig));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (next: LocalOcrConfig) => {
    setConfig(next);
    setSaving(true);
    try {
      await settingsClient.setPreference('ocr_config', JSON.stringify(next), 'ocr');
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await ocrApi.recognize(TEST_IMAGE);
      const text = (result.text || '').trim();
      setTestResult(text || t('settings.ocr.test_empty'));
    } catch (err) {
      setTestResult(
        t('settings.ocr.test_failed').replace(
          '{error}',
          err instanceof Error ? err.message : String(err),
        ),
      );
    } finally {
      setTesting(false);
    }
  };

  const available = Boolean(caps?.enabled && caps?.available);
  const engineLabel = caps?.selected_engine ?? t('settings.ocr.engine_none');
  const reason = caps?.reason || t('settings.ocr.install_hint');

  return (
    <div data-testid="settings-local-ocr" className="space-y-3 rounded border border-border p-3">
      <div>
        <h3 className="text-sm font-semibold text-text">{t('settings.ocr.title')}</h3>
        <p className="mt-0.5 text-xs text-muted">{t('settings.ocr.desc')}</p>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 ${
            available
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-border bg-bg-subtle text-muted'
          }`}
        >
          {available
            ? t('settings.ocr.available').replace('{engine}', engineLabel)
            : t('settings.ocr.unavailable')}
        </span>
        {!available && <span className="text-muted">{reason}</span>}
        {saving && <span className="text-muted">{t('settings.ocr.saving')}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          data-testid="settings-ocr-test"
          disabled={!available || testing}
          onClick={runTest}
          className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text disabled:cursor-not-allowed disabled:opacity-50"
        >
          {testing ? t('settings.ocr.testing') : t('settings.ocr.test')}
        </button>
        {testResult && (
          <span data-testid="settings-ocr-test-result" className="text-muted">
            {testResult}
          </span>
        )}
      </div>

      <label className="flex items-center justify-between gap-3 text-xs">
        <span className="text-text">{t('settings.ocr.engine')}</span>
        <select
          data-testid="settings-ocr-engine"
          value={config.engine}
          onChange={(e) => save({ ...config, engine: e.target.value as LocalOcrConfig['engine'] })}
          className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text"
        >
          <option value="auto">{t('settings.ocr.engine_auto')}</option>
          <option value="rapidocr">RapidOCR</option>
          <option value="tesseract">Tesseract</option>
        </select>
      </label>

      <label className="flex items-center justify-between gap-3 text-xs">
        <span className="text-text">{t('settings.ocr.lang')}</span>
        <select
          data-testid="settings-ocr-lang"
          value={config.lang}
          onChange={(e) => save({ ...config, lang: e.target.value as LocalOcrConfig['lang'] })}
          className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text"
        >
          <option value="auto">{t('settings.ocr.lang_auto')}</option>
          <option value="ch">{t('settings.ocr.lang_ch')}</option>
          <option value="en">{t('settings.ocr.lang_en')}</option>
        </select>
      </label>

      <label className="flex items-start justify-between gap-3 text-xs">
        <span>
          <span className="block text-text">{t('settings.ocr.prefer_local')}</span>
          <span className="block text-muted">{t('settings.ocr.prefer_local_desc')}</span>
        </span>
        <input
          type="checkbox"
          data-testid="settings-ocr-prefer-local"
          checked={config.prefer_local_for_images}
          onChange={(e) => save({ ...config, prefer_local_for_images: e.target.checked })}
        />
      </label>
    </div>
  );
}
