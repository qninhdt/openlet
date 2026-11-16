import { COLOR_BY_ID } from '@/vendor/bloub/skins';

const appearances: Record<string, { shape: string; color: string; expression: string }> = {
  Atlas: { shape: 'hexagone', color: 'ambre', expression: 'attentif' },
  Scout: { shape: 'galet', color: 'bleu', expression: 'curieux' },
  Forge: { shape: 'squircle', color: 'vert', expression: 'neutre' },
  Pulse: { shape: 'nuage', color: 'violet', expression: 'heureux' },
  Sage: { shape: 'cercle', color: 'turquoise', expression: 'attentif' },
};

export function agentAppearance(name: string) {
  const appearance = appearances[name] ?? appearances.Forge;
  return {
    ...appearance,
    background: COLOR_BY_ID.get(appearance.color)!.hex,
    foreground: COLOR_BY_ID.get('encre')!.hex,
  };
}
