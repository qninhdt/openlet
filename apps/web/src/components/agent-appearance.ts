import { COLOR_BY_ID } from '@/vendor/bloub/skins';

export type AgentAppearance = { shape: string; color: string };

const appearances: Record<string, { shape: string; color: string; expression: string }> = {
  Atlas: { shape: 'hexagone', color: 'ambre', expression: 'attentif' },
  Scout: { shape: 'galet', color: 'bleu', expression: 'curieux' },
  Forge: { shape: 'squircle', color: 'vert', expression: 'neutre' },
  Pulse: { shape: 'nuage', color: 'violet', expression: 'heureux' },
  Sage: { shape: 'cercle', color: 'turquoise', expression: 'attentif' },
};

export function agentAppearance(name: string, saved?: AgentAppearance | null) {
  const appearance = { ...(appearances[name] ?? appearances.Forge), ...saved };
  return {
    ...appearance,
    background: (COLOR_BY_ID.get(appearance.color) ?? COLOR_BY_ID.get('vert')!).hex,
    foreground: COLOR_BY_ID.get('encre')!.hex,
  };
}
