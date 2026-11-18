import { fileBlob, type StorageNode } from './storage-preview.js';

export async function readTextFile(node: StorageNode) {
  const blob = await fileBlob(node);
  const truncated = blob.size > 1_000_000;
  const bytes = new Uint8Array(await blob.slice(0, 1_000_000).arrayBuffer());
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes, { stream: truncated });
  if (text.includes('\0'))
    throw new Error('This file contains binary data. Download it to open the original file.');
  return {
    node,
    text: text.replace(/\r\n/g, '\n'),
    bom: bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191,
    crlf: text.includes('\r\n'),
    truncated,
  };
}

export function serializeTextFile(text: string, format: { bom: boolean; crlf: boolean }) {
  return (format.bom ? '\uFEFF' : '') + (format.crlf ? text.replace(/\n/g, '\r\n') : text);
}
