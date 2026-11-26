import { usePreferences } from '@/lib/backend';
// React port of OpenBot ComposerEditor at 5c1cae0; DOM/selection helpers are in ./openbot.
// PolyForm Noncommercial 1.0.0: https://polyformproject.org/licenses/noncommercial/1.0.0/
// Required Notice: Copyright 2026 Synthetify Labs spółka z ograniczoną odpowiedzialnością.
// Required Notice: For a commercial license, contact licenses@openbot.run.
import { useEffect, useCallback, useId, useLayoutEffect, useRef, useState } from 'react';
import { fileLink, fileReferences, letfsLinkPattern, type FileRef } from '@/lib/file-refs';
import { fileReferenceStyles } from '@/components/ui/styles';
import { FileIcon } from '@/components/storage/file-icon';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { useAgentPreview } from './agent-preview';
import { useFileChoices } from './file-picker';
import {
  automaticMentionSpaceAtCaretBoundary,
  editorText,
  editorTextOffset,
  insertLineBreak,
  insertPlainText,
  mentionTokenAtCaretBoundary,
  placeCaretAtChildOffset,
  placeCaretAtEnd,
  placeSerializedCaret,
  rangeFromTextOffsets,
  readEditorSelection,
  restoreEditorSelection,
  serializedEditorSelection,
  serializeEditor,
  type ComposerSelection,
} from './openbot/composer-dom';

export type ComposerEditorHandle = {
  insertFile: (ref: FileRef, selection?: ComposerSelection) => void;
  clear: () => void;
  submit: () => void;
};
type Mention = { start: number; end: number; query: string };

// OpenBot's attachment tokens are native, non-editable DOM nodes, so the browser owns their undo history.
function createAttachmentToken(ref: FileRef) {
  const token = document.createElement('span');
  token.contentEditable = 'false';
  token.dataset.attachmentReferenceId = `${ref.storage_id}/${ref.node_id}`;
  token.dataset.attachmentReferenceName = ref.label;
  if (ref.kind === 'folder') token.dataset.attachmentReferenceKind = 'folder';
  token.className = fileReferenceStyles;
  token.setAttribute('role', 'button');
  token.tabIndex = 0;
  token.setAttribute('aria-label', ref.label);
  token.title = ref.name ?? ref.label;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 20 20');
  svg.setAttribute('class', 'size-4 shrink-0 fill-none stroke-current text-muted-foreground');
  svg.setAttribute('aria-hidden', 'true');
  const paths =
    ref.kind === 'folder'
      ? ['M2.5 5h6l2 2h7v8h-15z']
      : ['M5 2.75h6l4 4v10.5H5z', 'M11 2.75v4h4M7.5 11h5M7.5 14h5'];
  for (const d of paths) {
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  const name = document.createElement('span');
  name.className = 'truncate';
  name.textContent = ref.label;
  token.append(svg, name);
  return token;
}
function renderEditorValue(editor: HTMLDivElement, value: string) {
  editor.replaceChildren();
  let cursor = 0;
  for (const match of value.matchAll(letfsLinkPattern())) {
    if (match.index > cursor)
      editor.append(document.createTextNode(value.slice(cursor, match.index)));
    editor.append(createAttachmentToken(fileReferences(match[0])[0]));
    cursor = match.index + match[0].length;
  }
  if (cursor < value.length) editor.append(document.createTextNode(value.slice(cursor)));
  if (value.endsWith('\n')) editor.append(document.createElement('br'));
}

export function ComposerEditor({ onEmptyChange }: { onEmptyChange: (empty: boolean) => void }) {
  const p = useAgentPreview();
  const preferences = usePreferences();
  const editor = useRef<HTMLDivElement>(null);
  const placeholder = useRef<HTMLSpanElement>(null);
  const composing = useRef(false);
  const empty = useRef(true);
  const savedSelection = useRef<ComposerSelection | null>(null);
  const [mention, setMention] = useState<Mention | null>(null);
  const [active, setActive] = useState(0);
  const [editing, setEditing] = useState<HTMLElement | null>(null);
  const [label, setLabel] = useState('');
  const optionsId = useId();
  const files = useFileChoices(!!mention, mention?.query ?? '');
  const choices = files.nodes.filter((node) =>
    node.name.toLowerCase().includes((mention?.query ?? '').toLowerCase()),
  );

  const latest = useRef({ p, onEmptyChange });
  useLayoutEffect(() => {
    latest.current = { p, onEmptyChange };
  });
  const emitValue = useCallback(() => {
    const { p, onEmptyChange } = latest.current;
    const surface = editor.current;
    if (!surface) return;
    const value = serializeEditor(surface);
    p.setDraft(p.resource.id, value);
    if (placeholder.current) placeholder.current.hidden = !!value;
    const nextEmpty = !value.trim();
    if (empty.current !== nextEmpty) {
      empty.current = nextEmpty;
      onEmptyChange(nextEmpty);
    }
    savedSelection.current = serializedEditorSelection(surface);
  }, []);
  const updateMention = useCallback(() => {
    const surface = editor.current;
    if (!surface || composing.current) return;
    const selection = readEditorSelection(surface);
    const before =
      selection && selection.anchor === selection.focus
        ? editorText(surface).slice(0, selection.focus)
        : '';
    const match = before.match(/(?:^|\s)@([^@\n\uFFFC]{0,60})$/u);
    if (!match) {
      setMention((previous) => (previous === null ? previous : null));
      return;
    }
    const next = {
      start: before.length - match[1].length - 1,
      end: before.length,
      query: match[1],
    };
    setMention((previous) =>
      previous?.start === next.start && previous.end === next.end && previous.query === next.query
        ? previous
        : next,
    );
    setActive(0);
  }, []);
  const submit = useCallback(() => {
    const { p } = latest.current;
    if (!editor.current || composing.current || p.session.uploads.length) return;
    void p.send(serializeEditor(editor.current));
  }, []);
  const insertFile = useCallback(
    (ref: FileRef, selection?: ComposerSelection) => {
      const surface = editor.current;
      if (!surface) return;
      // An upload may finish during IME: leave the browser's composition buffer untouched.
      if (composing.current) {
        pendingFiles.current.push({ ref, selection });
        return;
      }
      surface.focus({ preventScroll: true });
      const saved = savedSelection.current;
      const at = selection ?? (saved ? { start: saved.end, end: saved.end } : null);
      if (at) {
        placeSerializedCaret(surface, at.start);
        const start = surface.ownerDocument.getSelection()?.getRangeAt(0).cloneRange();
        placeSerializedCaret(surface, at.end);
        const end = surface.ownerDocument.getSelection()?.getRangeAt(0);
        if (start && end) {
          start.setEnd(end.endContainer, end.endOffset);
          const current = surface.ownerDocument.getSelection();
          current?.removeAllRanges();
          current?.addRange(start);
        }
      } else placeCaretAtEnd(surface);
      const token = createAttachmentToken(ref);
      // insertHTML is the same native editing path OpenBot uses, preserving undo/redo and selection.
      const range = surface.ownerDocument.getSelection()?.getRangeAt(0);
      const before = range
        ? editorText(surface).slice(
            0,
            editorTextOffset(surface, range.startContainer, range.startOffset),
          )
        : '';
      const separator = range?.collapsed && before && !/\s$/.test(before) ? ' ' : '';
      document.execCommand('insertHTML', false, separator + token.outerHTML + ' ');
      emitValue();
      setMention(null);
    },
    [emitValue],
  );
  const pendingFiles = useRef<{ ref: FileRef; selection?: ComposerSelection }[]>([]);

  useLayoutEffect(() => {
    const surface = editor.current!;
    const value = p.drafts.get(p.resource.id) ?? '';
    composing.current = false;
    renderEditorValue(surface, value);
    empty.current = !value.trim();
    onEmptyChange(empty.current);
    placeholder.current!.hidden = !!value;
    savedSelection.current = null;
    const handle = {
      insertFile: (ref: FileRef, selection?: ComposerSelection) => insertFile(ref, selection),
      clear: () => {
        surface.replaceChildren();
        emitValue();
        setMention(null);
      },
      submit: () => submit(),
    };
    p.composers.set(p.resource.id, handle);
    const pending = pendingFiles.current;
    return () => {
      p.composers.delete(p.resource.id);
      for (const item of pending.splice(0)) {
        const draft = p.drafts.get(p.resource.id) ?? '';
        p.setDraft(p.resource.id, draft + ' ' + fileLink(item.ref) + ' ');
      }
    };
  }, [p.resource.id, p.drafts, p.composers, onEmptyChange, emitValue, insertFile, submit]);

  // Native beforeinput carries inputType/data consistently; React's synthetic beforeinput does not.
  const beforeInput = useCallback(
    (event: InputEvent) => {
      if (!editor.current || composing.current || event.isComposing) return;
      const lineBreak =
        event.inputType === 'insertLineBreak' || event.inputType === 'insertParagraph';
      if (!lineBreak && (event.inputType !== 'insertText' || !event.data)) return;
      event.preventDefault();
      if (lineBreak) insertLineBreak(editor.current);
      else insertPlainText(editor.current, event.data!);
      emitValue();
      updateMention();
    },
    [emitValue, updateMention],
  );
  useEffect(() => {
    const surface = editor.current!;
    const before = (event: InputEvent) => beforeInput(event);
    surface.addEventListener('beforeinput', before);
    return () => surface.removeEventListener('beforeinput', before);
  }, [beforeInput]);

  function choose(index: number) {
    const node = choices[index];
    const surface = editor.current;
    if (!node || !surface || !mention) return;
    const range = rangeFromTextOffsets(surface, mention.start, mention.end);
    if (!range) return;
    const selection = surface.ownerDocument.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const at = serializedEditorSelection(surface);
    setMention(null);
    void p.attachFile(node, false, node.name, at);
  }
  function editToken(token: HTMLElement) {
    setLabel(token.dataset.attachmentReferenceName ?? '');
    setEditing(token);
  }
  function removeToken(token: HTMLElement) {
    const parent = token.parentNode;
    if (!parent) return;
    const offset = Array.from(parent.childNodes).indexOf(token);
    token.remove();
    editor.current!.focus();
    placeCaretAtChildOffset(parent, Math.min(offset, parent.childNodes.length));
    emitValue();
    setMention(null);
  }
  return (
    <div className="relative min-w-0 flex-1">
      <span
        ref={placeholder}
        aria-hidden="true"
        className="pointer-events-none absolute top-1 left-1 text-sm leading-5 text-muted-foreground"
      >
        Message {p.profile.name}…
      </span>
      <div
        ref={editor}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        tabIndex={0}
        aria-label={`Message ${p.profile.name}`}
        aria-multiline="true"
        aria-autocomplete="list"
        aria-controls={mention ? optionsId : undefined}
        aria-expanded={!!mention}
        aria-activedescendant={mention && choices[active] ? `${optionsId}-${active}` : undefined}
        spellCheck
        className="max-h-48 min-h-7 w-full overflow-y-auto bg-transparent px-1 py-1 text-sm leading-5 whitespace-pre-wrap break-words caret-foreground outline-none focus:outline-none"
        onFocus={() => {
          const surface = editor.current!;
          if (!readEditorSelection(surface)) placeCaretAtEnd(surface);
        }}
        onInput={() => {
          emitValue();
          updateMention();
        }}
        onClick={(event) => {
          const token = (event.target as HTMLElement).closest<HTMLElement>(
            '[data-attachment-reference-id]',
          );
          if (token) {
            event.preventDefault();
            editToken(token);
          } else updateMention();
        }}
        onKeyUp={(event) => {
          if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) updateMention();
        }}
        onKeyDown={(event) => {
          const surface = editor.current!;
          if (
            composing.current ||
            event.nativeEvent.isComposing ||
            event.keyCode === 229 ||
            event.key === 'Process'
          )
            return;
          const token = (event.target as HTMLElement).closest<HTMLElement>(
            '[data-attachment-reference-id]',
          );
          if (token) {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              editToken(token);
              return;
            }
            if (event.key === 'Backspace' || event.key === 'Delete') {
              event.preventDefault();
              removeToken(token);
              return;
            }
          }
          if (mention) {
            if (event.key === 'Escape') {
              event.preventDefault();
              setMention(null);
              return;
            }
            if (choices.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
              event.preventDefault();
              setActive(
                (index) =>
                  (index + (event.key === 'ArrowDown' ? 1 : choices.length - 1)) % choices.length,
              );
              return;
            }
            if (
              choices.length &&
              (event.key === 'Enter' || event.key === 'Tab') &&
              !event.shiftKey
            ) {
              event.preventDefault();
              choose(active);
              return;
            }
          }
          if (event.key === 'Backspace' || event.key === 'Delete') {
            const selection = surface.ownerDocument.getSelection();
            const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
            if (range?.collapsed && surface.contains(range.commonAncestorContainer)) {
              const space =
                event.key === 'Backspace'
                  ? automaticMentionSpaceAtCaretBoundary(surface, range)
                  : null;
              if (space) {
                event.preventDefault();
                space.text.deleteData(0, 1);
                placeCaretAtChildOffset(
                  space.token.parentNode!,
                  Array.from(space.token.parentNode!.childNodes).indexOf(space.token) + 1,
                );
                emitValue();
                return;
              }
              const adjacent = mentionTokenAtCaretBoundary(surface, range, event.key);
              if (adjacent) {
                event.preventDefault();
                removeToken(adjacent);
                return;
              }
            }
          }
          if (event.key === 'Enter') {
            event.preventDefault();
            if (
              event.shiftKey ||
              (preferences.sendShortcut === 'modifier-enter' && !event.ctrlKey && !event.metaKey)
            ) {
              insertLineBreak(surface);
              emitValue();
              updateMention();
            } else submit();
          }
        }}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
          emitValue();
          updateMention();
          for (const item of pendingFiles.current.splice(0)) insertFile(item.ref, item.selection);
        }}
        onPaste={(event) => {
          event.preventDefault();
          const uploads = Array.from(event.clipboardData.files);
          const surface = editor.current!;
          if (uploads.length) {
            const at = serializedEditorSelection(surface);
            void (async () => {
              for (const [index, file] of uploads.entries())
                await p.queueUpload(file, index === 0 ? at : undefined);
            })();
          } else {
            insertPlainText(surface, event.clipboardData.getData('text/plain'));
            emitValue();
            updateMention();
          }
        }}
        onCopy={(event) => {
          const surface = editor.current!;
          const at = serializedEditorSelection(surface);
          if (!surface.ownerDocument.getSelection()?.containsNode(surface, true)) return;
          event.preventDefault();
          event.clipboardData.setData(
            'text/plain',
            serializeEditor(surface).slice(at.start, at.end),
          );
        }}
        onBlur={() => {
          composing.current = false;
          window.setTimeout(() => {
            if (editor.current?.ownerDocument.activeElement !== editor.current) setMention(null);
          }, 100);
        }}
      />
      {mention && (
        <div
          id={optionsId}
          role="listbox"
          aria-label="Files and folders"
          className="absolute bottom-full left-0 z-30 mb-2 max-h-64 w-72 max-w-[calc(100vw-32px)] overflow-auto rounded-xl border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {choices.map((node, index) => (
            <button
              key={`${node.storage}/${node.id}`}
              id={`${optionsId}-${index}`}
              type="button"
              role="option"
              aria-selected={active === index}
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
              className="flex w-full items-center gap-2 rounded-md p-2 text-left text-caption hover:bg-accent aria-selected:bg-accent"
            >
              <FileIcon node={node} />
              <span className="truncate">{node.name}</span>
            </button>
          ))}
          {!choices.length && (
            <p className="p-3 text-xs text-muted-foreground">
              {files.query.isFetching
                ? 'Searching…'
                : (files.query.error?.message ?? 'No files or folders found.')}
            </p>
          )}
        </div>
      )}
      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            editor.current?.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>Attachment label</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!editing || !label.trim()) return;
              const selection = readEditorSelection(editor.current!);
              const [storage_id, node_id] = editing.dataset.attachmentReferenceId!.split('/');
              editing.replaceWith(
                createAttachmentToken({
                  storage_id,
                  node_id,
                  label: label.trim(),
                  name: editing.title,
                  kind: editing.dataset.attachmentReferenceKind === 'folder' ? 'folder' : 'file',
                }),
              );
              emitValue();
              if (selection) restoreEditorSelection(editor.current!, selection);
              setEditing(null);
            }}
          >
            <Input
              autoFocus
              aria-label="Attachment label"
              value={label}
              maxLength={255}
              onChange={(event) => setLabel(event.target.value)}
            />
            <DialogFooter className="mt-4">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  const [storage_id, node_id] = editing!.dataset.attachmentReferenceId!.split('/');
                  void p.openFileReference({ storage_id, node_id, label });
                  setEditing(null);
                }}
              >
                View file
              </Button>
              <Button type="submit" disabled={!label.trim()}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
