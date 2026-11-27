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

export const letfsLinkPattern = () =>
  /(?<!!)\[((?:\\.|[^\]\\\n]){1,1024})\]\(\/letfs\/([\w-]+)\/([\w-]+)(?:\/[^)\s]*)?\)/g;

export function fileReferences(content: string): FileRef[] {
  return [...content.matchAll(letfsLinkPattern())].map((m) => ({
    label: m[1].replace(/\\(.)/g, '$1'),
    storage_id: m[2],
    node_id: m[3],
  }));
}

export function fileLink(ref: FileRef) {
  const label = ref.label
    .replace(/\n/g, ' ')
    .slice(0, 255)
    .replace(/[\\[\]]/g, '\\$&');
  return `[${label}](/letfs/${ref.storage_id}/${ref.node_id})`;
}

export function fileText(content: string) {
  return content.replace(letfsLinkPattern(), (_, label: string) => label.replace(/\\(.)/g, '$1'));
}

export function fileMarkdown(content: string) {
  return mapMarkdownText(content, markdownReferences);
}

function markdownReferences(content: string) {
  return content.replace(
    letfsLinkPattern(),
    (_, rawLabel: string, storageId: string, nodeId: string) => {
      const label = rawLabel.replace(/\\(.)/g, '$1').replace(/[\\`*_[\]<>!]/g, '\\$&');
      return `[${label}](openlet-file:${storageId}/${nodeId})`;
    },
  );
}
