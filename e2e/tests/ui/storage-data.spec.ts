import { expect, test } from '@playwright/test';
import {
  ancestors,
  branch,
  NameConflict,
  restoreNode,
  rootId,
  seedStorage,
  storageRoots,
  transferNodes,
  trashNodes,
  validateName,
} from '../../../apps/web/src/lib/storage-preview.js';

test('filesystem transactions preserve subtrees, reject cycles and retain replaced files in Trash', () => {
  const roots = storageRoots({ id: 'test', agents: [] });
  const original = seedStorage(roots);
  const personal = roots[0].id;
  const team = roots[1].id;
  const folder = original.nodes.find(
    (node) => node.storage === personal && node.name === 'Documents',
  )!;
  const project = original.nodes.find(
    (node) => node.storage === personal && node.name === 'Projects',
  )!;
  expect(() => transferNodes(original, [folder.id], personal, project.id, false, 'ask')).toThrow(
    'itself',
  );
  const copied = transferNodes(original, [folder.id, project.id], team, rootId(team), true, 'keep');
  const target = copied.nodes.find(
    (node) => node.storage === team && node.name === 'Documents (2)',
  )!;
  expect(branch(copied.nodes, target.id).length).toBe(branch(original.nodes, folder.id).length);
  expect(branch(copied.nodes, target.id).every((node) => node.storage === team)).toBe(true);
  expect(() => transferNodes(original, [folder.id], team, rootId(team), true, 'ask')).toThrow(
    NameConflict,
  );
  const replaced = transferNodes(original, [folder.id], team, rootId(team), false, 'replace');
  const oldFolder = replaced.nodes.find(
    (node) => node.storage === team && node.name === 'Documents' && node.trashed,
  )!;
  expect(oldFolder).toBeTruthy();
  expect(branch(replaced.nodes, folder.id).every((node) => node.storage === team)).toBe(true);
  const trashed = trashNodes(replaced, [folder.id, project.id]);
  expect(trashed.nodes.filter((node) => node.trashed).length).toBe(2);
  expect(ancestors(trashed.nodes, project.id).some((node) => node.trashed)).toBe(true);
  const restored = restoreNode(trashed, folder.id);
  expect(restored.nodes.find((node) => node.id === folder.id)?.parent).toBe(rootId(team));
  expect(original.nodes.find((node) => node.id === folder.id)?.storage).toBe(personal);
  for (const invalid of ['', '..', 'a/b', 'a\0b']) expect(() => validateName(invalid)).toThrow();
});
