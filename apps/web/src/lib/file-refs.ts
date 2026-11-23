import { mapMarkdownText } from './markdown.js';

export type FileRef = {
  storage_id: string;
  node_id: string;
  label: string;
  kind?: 'file' | 'folder';
  name?: string;
  mime?: string;
  size?: number;
  version?: number;
};
export type MessageSource =
  | { kind: 'web'; url: string; title: string }
  | (FileRef & { kind: 'file' | 'folder'; page?: number; line?: number });

export const fileTokenPattern = () =>
  /:(?:file|folder)\[((?:\\.|[^\]\\\n]){1,1024})\]\{name=([\w:-]+)\/([\w:-]+)\}/g;
export function fileReferences(content: string): FileRef[] {
  return [...content.matchAll(fileTokenPattern())].map((m) => ({
    label: m[1].replace(/\\(.)/g, '$1'),
    storage_id: m[2],
    node_id: m[3],
    ...(m[0].startsWith(':folder[') ? { kind: 'folder' as const } : {}),
  }));
}
export function fileToken(ref: FileRef) {
  const label = ref.label
    .replace(/\n/g, ' ')
    .slice(0, 255)
    .replace(/[\\\[\]]/g, '\\$&');
  return `:${ref.kind === 'folder' ? 'folder' : 'file'}[${label}]{name=${ref.storage_id}/${ref.node_id}}`;
}
export function fileText(content: string) {
  return content.replace(fileTokenPattern(), (_, label: string) => label.replace(/\\(.)/g, '$1'));
}
export function fileMarkdown(content: string) {
  return mapMarkdownText(content, markdownReferences);
}

function markdownReferences(content: string) {
  let result = '',
    end = 0;
  for (const match of content.matchAll(fileTokenPattern())) {
    // A literal ! immediately before a file must not turn the reference into a Markdown image.
    result += content
      .slice(end, match.index)
      .replace(/(\\*)!$/, (_, slashes: string) => slashes + (slashes.length % 2 ? '' : '\\') + '!');
    const ref = fileReferences(match[0])[0];
    const label = ref.label.replace(/[\\`*_[\]<>!]/g, '\\$&');
    result += `[${label}](openlet-${ref.kind ?? 'file'}:${ref.storage_id}/${ref.node_id})`;
    end = match.index + match[0].length;
  }
  return result + content.slice(end);
}
