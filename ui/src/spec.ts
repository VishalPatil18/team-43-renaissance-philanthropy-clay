export interface CustomQuery { prompt: string; expect: string[] }

export interface PreviewFields {
  name: string; template: string; aoi: string; model: string; modelId: string; harness: string;
  toolset: string; trials: number; steps: number;
  maxUsd?: number; maxSeconds?: number; evalCapUsd?: number;
  /** More model IDs to compare with the first; each becomes a model variant. */
  compareModelIds?: string[];
  /** A free-form question instead of a library task (tasks.custom). */
  custom?: CustomQuery | null;
}

/** Same rule as claysandbox.platform.custom.slug: the first words, lower-case. */
export function slug(text: string): string {
  const words = text.toLowerCase().match(/[a-z0-9]+/g)?.slice(0, 6) ?? [];
  return words.join('-').slice(0, 40).replace(/^-+|-+$/g, '') || 'query';
}

/** Same rule as claysandbox.platform.query.config_name: us.amazon.nova-pro-v1:0 -> nova-pro-v1. */
export function configName(modelId: string): string {
  const name = (modelId.split('/').pop() ?? '')
    .replace(/^(us|eu|apac|global)\./, '').replace(/^[a-z]+\./, '').replace(/:\d+$/, '')
    .toLowerCase().replace(/[^a-z0-9.-]+/g, '-').replace(/^-+|-+$/g, '');
  return name || 'model';
}

export const splitLines = (text: string) => text.split(/[\n,]/).map(s => s.trim()).filter(Boolean);

/** The EvalSpec object the platform validates (contracts/spec.py). */
export function buildSpec(f: PreviewFields): Record<string, unknown> {
  const others = (f.compareModelIds ?? []).filter(m => m && m !== f.modelId);
  const ids = [f.modelId, ...others];
  let names = ids.map(configName);
  if (new Set(names).size !== names.length) names = names.map((n, i) => `${n}-${i + 1}`);
  const compare = others.length > 0;
  const custom = f.custom?.prompt.trim() ? f.custom : null;
  return {
    spec_version: 1, name: f.name,
    tasks: custom
      ? { custom: [{ id: slug(custom.prompt), prompt: custom.prompt.trim(), expect: custom.expect }] }
      : { templates: [f.template], aois: [f.aoi] },
    baseline: {
      name: compare ? names[0] : 'baseline',
      model: { name: f.model, params: { model_id: f.modelId } },
      harness: { name: f.harness, params: {} },
      toolset: f.toolset,
      tracer: { name: 'jsonl' },
    },
    ...(compare ? { variants: others.map((m, i) => ({ name: names[i + 1], override: { model: { params: { model_id: m } } } })) } : {}),
    evaluators: custom ? [{ name: 'expect', version: '1' }] : [{ name: 'workflow', version: '1' }, { name: 'output', version: '1' }],
    summary: { name: 'deterministic' },
    trials: f.trials, seed: 42,
    budget: {
      run: { max_steps: f.steps, max_usd: f.maxUsd ?? 0.1, max_seconds: f.maxSeconds ?? 240 },
      eval: { max_usd: f.evalCapUsd ?? 2 },
    },
    executor: { name: 'local', params: { max_parallel: Math.min(4, Math.max(2, ids.length)) } },
  };
}

/** JSON is a YAML 1.2 subset; platform serialization safely quotes free text. */
export function previewSpec(f: PreviewFields): string {
  return JSON.stringify(buildSpec(f), null, 2) + '\n';
}
