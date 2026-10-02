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
