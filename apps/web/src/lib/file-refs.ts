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

export const letfsLinkPattern = () =>
  /(?<!!)\[((?:\\.|[^\]\\\n]){1,1024})\]\(\/letfs\/([\w-]+)\/([\w-]+)(?:\/[^)\s]*)?\)/g;

export function fileReferences(content: string): FileRef[] {
  const legacy: FileRef[] = [...content.matchAll(fileTokenPattern())].map((m) => ({
    label: m[1].replace(/\\(.)/g, '$1'),
    storage_id: m[2],
    node_id: m[3],
    ...(m[0].startsWith(':folder[') ? { kind: 'folder' as const } : {}),
  }));
  const canonical: FileRef[] = [...content.matchAll(letfsLinkPattern())].map((m) => ({
    label: m[1].replace(/\\(.)/g, '$1'),
    storage_id: m[2],
    node_id: m[3],
  }));
  return [...canonical, ...legacy];
}

export function fileToken(ref: FileRef) {
  const label = ref.label
    .replace(/\n/g, ' ')
    .slice(0, 255)
    .replace(/[\\[\]]/g, '\\$&');
  return `:${ref.kind === 'folder' ? 'folder' : 'file'}[${label}]{name=${ref.storage_id}/${ref.node_id}}`;
}

export function fileLink(ref: FileRef) {
  const label = ref.label
    .replace(/\n/g, ' ')
    .slice(0, 255)
    .replace(/[\\[\]]/g, '\\$&');
  return `[${label}](/letfs/${ref.storage_id}/${ref.node_id})`;
}

export function fileText(content: string) {
  return content
    .replace(letfsLinkPattern(), (_, label: string) => label.replace(/\\(.)/g, '$1'))
    .replace(fileTokenPattern(), (_, label: string) => label.replace(/\\(.)/g, '$1'));
}

export function fileMarkdown(content: string) {
  return mapMarkdownText(content, markdownReferences);
}

function markdownReferences(content: string) {
  // Rewrite CommonMark /letfs/<storage_id>/<node_id> links into openlet-file chips first.
  const withCanonical = content.replace(
    letfsLinkPattern(),
    (_, rawLabel: string, storageId: string, nodeId: string) => {
      const label = rawLabel.replace(/\\(.)/g, '$1').replace(/[\\`*_[\]<>!]/g, '\\$&');
      return `[${label}](openlet-file:${storageId}/${nodeId})`;
    },
  );
  let result = '',
    end = 0;
  for (const match of withCanonical.matchAll(fileTokenPattern())) {
    // A literal ! immediately before a file must not turn the reference into a Markdown image.
    result += withCanonical
      .slice(end, match.index)
      .replace(/(\\*)!$/, (_, slashes: string) => slashes + (slashes.length % 2 ? '' : '\\') + '!');
    const ref = fileReferences(match[0])[0];
    const label = ref.label.replace(/[\\`*_[\]<>!]/g, '\\$&');
    result += `[${label}](openlet-${ref.kind ?? 'file'}:${ref.storage_id}/${ref.node_id})`;
    end = match.index + match[0].length;
  }
  return result + withCanonical.slice(end);
}
