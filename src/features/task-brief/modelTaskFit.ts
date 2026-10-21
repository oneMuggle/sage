import type { CandidateModel } from '../../entities/model-catalog/types';

export function modelTaskFit(model: CandidateModel, needsTools: boolean) {
  const capabilities = model.capabilities;
  const known = ['tools', 'tool_calling', 'function_calling', 'supports_tools']
    .map((key) => capabilities?.[key])
    .filter((value): value is boolean => typeof value === 'boolean');
  const tools =
    !known.length || (known.includes(true) && known.includes(false))
      ? 'unknown'
      : known[0]
        ? 'supported'
        : 'unsupported';
  return {
    eligible: !needsTools || tools === 'supported',
    tools,
    knownPrice: model.price.input_per_million !== null && model.price.output_per_million !== null,
  };
}

export function formatModelTaskFitSummary(model: CandidateModel, needsTools: boolean): string {
  const fit = modelTaskFit(model, needsTools);
  /* v8 ignore start */
  const eligLabel = fit.eligible ? 'eligible' : 'ineligible';
  const priceLabel = fit.knownPrice ? 'known' : 'unknown';
  /* v8 ignore stop */
  return `model-fit: ${model.model_key.provider}/${model.model_key.model_id} · ${eligLabel} · tools=${fit.tools} · price=${priceLabel}`;
}

export function formatModelTaskFitJson(model: CandidateModel, needsTools: boolean): string {
  const fit = modelTaskFit(model, needsTools);
  return JSON.stringify(
    {
      provider: model.model_key.provider,
      modelId: model.model_key.model_id,
      needsTools: Boolean(needsTools),
      eligible: fit.eligible,
      tools: fit.tools,
      knownPrice: fit.knownPrice,
    },
    null,
    2,
  );
}
