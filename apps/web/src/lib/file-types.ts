import fileTypes from '../../../../packages/contracts/file-types.json' with { type: 'json' };

const { text, blob }: Record<'text' | 'blob', Record<string, string>> = fileTypes;

export function classifyExtension(extension: string) {
  const ext = extension.replace(/^\./, '').toLowerCase();
  if (Object.hasOwn(text, ext)) return { kind: 'text' as const, mediaType: text[ext] };
  if (Object.hasOwn(blob, ext)) return { kind: 'blob' as const, mediaType: blob[ext] };
  return { kind: 'unsupported' as const, mediaType: '' };
}

export function classifyFile(name: string) {
  const base = name.slice(name.lastIndexOf('/') + 1);
  const dot = base.lastIndexOf('.');
  return classifyExtension(dot > 0 ? base.slice(dot) : '');
}
