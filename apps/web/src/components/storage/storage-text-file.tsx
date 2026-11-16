import { useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker } from '@tanstack/react-router';
import CodeMirror, { Prec, type Extension } from '@uiw/react-codemirror';
import { EditorView } from '@codemirror/view';
import { LanguageDescription } from '@codemirror/language';
import { languages } from '@codemirror/language-data';
import { useTheme } from 'next-themes';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Papa from 'papaparse';
import { Copy, Download, Save, WrapText } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { formatBytes } from '@/lib/storage-preview';
import { fileBlob, type StorageNode, type StorageTextSession } from './storage-context';

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', color: 'var(--foreground)', height: '100%' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { overflow: 'auto', fontFamily: 'ui-monospace, monospace', fontSize: '13px' },
  '.cm-content': { padding: '16px 0', caretColor: 'var(--foreground)' },
  '.cm-line': { padding: '0 16px' },
  '.cm-gutters': {
    backgroundColor: 'var(--sidebar)',
    color: 'var(--muted-foreground)',
    borderColor: 'var(--border)',
  },
  '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--accent)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {
    backgroundColor: 'var(--accent)',
  },
  '.cm-cursor': { borderLeftColor: 'var(--foreground)' },
  '.cm-panels, .cm-tooltip': {
    backgroundColor: 'var(--popover)',
    color: 'var(--popover-foreground)',
    borderColor: 'var(--border)',
  },
});

const csvCellClasses =
  'min-w-25 max-w-90 border px-3 py-1.5 align-top whitespace-pre-wrap wrap-anywhere';

function CsvPreview({ text, tabSeparated }: { text: string; tabSeparated: boolean }) {
  const parsed = useMemo(
    () =>
      Papa.parse<string[]>(text, {
        delimiter: tabSeparated ? '\t' : '',
        preview: 501,
        skipEmptyLines: true,
      }),
    [text, tabSeparated],
  );
  const limited =
    parsed.meta.truncated || parsed.data.length > 500 || parsed.data.some((row) => row.length > 50);
  const error = parsed.errors.find((error) => error.code !== 'UndetectableDelimiter');
  return (
    <div className="min-h-0 min-w-0 flex-1 overflow-auto">
      {error && (
        <p role="alert" className="border-b p-3 text-sm text-muted-foreground">
          {error.message} Fix the source to render all cells correctly.
        </p>
      )}
      <table className="w-full border-collapse text-sm" aria-label="CSV preview">
        <tbody>
          {parsed.data.slice(0, 500).map((row, i) => (
            <tr key={i}>
              <th scope="row" className={`${csvCellClasses} bg-muted text-left font-medium`}>
                {i + 1}
              </th>
              {row.slice(0, 50).map((cell, j) =>
                i === 0 ? (
                  <th
                    scope="col"
                    key={j}
                    className={`${csvCellClasses} bg-muted text-left font-medium`}
                  >
                    {cell}
                  </th>
                ) : (
                  <td key={j} className={csvCellClasses}>
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {limited && (
        <p className="p-3 text-sm text-muted-foreground">
          Preview shows up to 500 rows and 50 columns. Source retains the full loaded text.
        </p>
      )}
    </div>
  );
}

export type TextFileAccess = {
  writable: boolean;
  saveText: (node: StorageNode, text: string) => Promise<StorageNode>;
  getTextSession: () => StorageTextSession | null;
  setTextSession: (session: StorageTextSession | null) => void;
};

export function TextFile({
  node,
  writable: canWrite,
  saveText,
  getTextSession,
  setTextSession,
  onDownload,
  active = true,
}: { node: StorageNode; onDownload: () => void; active?: boolean } & TextFileAccess) {
  const { resolvedTheme } = useTheme();
  const [openedNode] = useState(node);
  const [cached] = useState(() => {
    const session = getTextSession();
    return session?.node.id === node.id &&
      ((session.node.blob === node.blob && session.node.updated === node.updated) ||
        (session.draft !== undefined && session.draft !== session.text))
      ? session
      : undefined;
  });
  const markdown = /markdown/.test(node.mime) || /\.(md|mdx|markdown)$/i.test(node.name);
  const csv = /csv|tab-separated-values/.test(node.mime) || /\.(csv|tsv)$/i.test(node.name);
  const html = /html/.test(node.mime) || /\.html?$/i.test(node.name);
  const rendered = markdown || csv || html;
  const [source, setSource] = useState(cached?.source ?? !rendered);
  const [loaded, setLoaded] = useState<
    | {
        node: StorageNode;
        text: string;
        bom: boolean;
        crlf: boolean;
        truncated: boolean;
      }
    | undefined
  >(cached);
  const [draft, setDraft] = useState<string | undefined>(cached?.draft);
  const [error, setError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);
  const [wrap, setWrap] = useState(true);
  const [language, setLanguage] = useState<Extension>([]);
  const scroll = useRef(cached?.scroll ?? { source: 0, preview: 0 });
  const preview = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!source && preview.current) preview.current.scrollTop = scroll.current.preview;
  }, [source, loaded]);
  const saveButton = useRef<HTMLButtonElement>(null);
  const content = draft ?? loaded?.text ?? '';
  const dirty = loaded !== undefined && content !== loaded.text;
  const writable = canWrite && !loaded?.truncated;
  const blocker = useBlocker({
    shouldBlockFn: () => saving,
    enableBeforeUnload: saving,
    withResolver: true,
  });

  useEffect(() => {
    if (cached) return;
    let alive = true;
    void fileBlob(openedNode)
      .then(async (blob) => {
        const truncated = blob.size > 1_000_000;
        const bytes = new Uint8Array(await blob.slice(0, 1_000_000).arrayBuffer());
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes, { stream: truncated });
        if (text.includes('\0'))
          throw new Error('This file contains binary data and cannot be edited as text.');
        if (alive)
          setLoaded({
            node: openedNode,
            text: text.replace(/\r\n/g, '\n'),
            bom: bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191,
            crlf: text.includes('\r\n'),
            truncated,
          });
      })
      .catch(
        () =>
          alive &&
          setError(
            'Could not open this file as UTF-8 text. Download it to open the original file.',
          ),
      );
    return () => {
      alive = false;
    };
  }, [openedNode, cached]);

  // The mobile/desktop shell remounts its content, so keep the active draft above it.
  useEffect(() => {
    if (loaded) setTextSession({ ...loaded, draft, source, scroll: scroll.current });
  }, [loaded, draft, source, setTextSession]);

  useEffect(() => {
    let alive = true;
    const description = LanguageDescription.matchFilename(languages, node.name);
    if (description)
      void description
        .load()
        .then((support) => {
          if (alive) setLanguage(support);
        })
        .catch(() => {});
    return () => {
      alive = false;
    };
  }, [node.name]);

  const extensions = useMemo(
    () => [
      Prec.highest(editorTheme),
      language,
      EditorView.contentAttributes.of({ 'aria-label': `Edit ${node.name}` }),
      ...(wrap ? [EditorView.lineWrapping] : []),
    ],
    [language, node.name, wrap],
  );

  async function save() {
    if (!loaded || !dirty || saving || !writable) return;
    setSaving(true);
    setSaveError('');
    try {
      const text =
        (loaded.bom ? '\uFEFF' : '') + (loaded.crlf ? content.replace(/\n/g, '\r\n') : content);
      const updated = await saveText(loaded.node, text);
      setLoaded({ ...loaded, node: updated, text: content });
      setDraft(undefined);
      toast.success('File saved');
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : 'Could not save. Your changes are still in the editor.',
      );
    } finally {
      setSaving(false);
    }
  }

  if (error)
    return (
      <p
        role="alert"
        className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground"
      >
        {error}
      </p>
    );
  if (!loaded)
    return (
      <p
        role="status"
        className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground"
      >
        Loading text…
      </p>
    );
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col bg-sidebar"
      onScrollCapture={(event) => {
        const target = event.target as HTMLElement;
        if (target.matches('.cm-scroller')) scroll.current.source = target.scrollTop;
        else if (target.matches('article,.storage-csv-preview'))
          scroll.current.preview = target.scrollTop;
        if (loaded) setTextSession({ ...loaded, draft, source, scroll: scroll.current });
      }}
      onKeyDown={(event) => {
        if (active && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          saveButton.current?.click();
        }
      }}
    >
      <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/40 px-3 py-1.5">
        <Tabs
          value={source ? 'source' : 'preview'}
          onValueChange={(value) => setSource(value === 'source')}
        >
          <TabsList className="h-7! border border-border bg-sidebar p-0.5">
            {rendered && (
              <TabsTrigger
                className="px-3 py-0.5 text-caption data-active:bg-accent data-active:shadow-none"
                value="preview"
              >
                Preview
              </TabsTrigger>
            )}
            <TabsTrigger
              className="px-3 py-0.5 text-caption data-active:bg-accent data-active:shadow-none"
              value="source"
            >
              Code
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <span className="hidden text-xs tabular-nums text-muted-foreground sm:inline">
          {content ? content.replace(/\n$/, '').split('\n').length : 0} lines ·{' '}
          {formatBytes(new Blob([content]).size)}
        </span>
        <span role="status" className="text-xs text-muted-foreground">
          {loaded.truncated
            ? 'Read-only · first 1 MB'
            : !writable
              ? 'Read-only'
              : saving
                ? 'Saving…'
                : dirty
                  ? 'Unsaved changes'
                  : ''}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {source && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Toggle line wrap"
              aria-pressed={wrap}
              title="Line wrap"
              onClick={() => setWrap(!wrap)}
            >
              <WrapText />
            </Button>
          )}
          <div className="flex items-center overflow-hidden rounded-md border [&>button]:rounded-none [&>button+button]:border-l">
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Copy file text"
              title="Copy file text"
              onClick={() =>
                void navigator.clipboard.writeText(content).then(
                  () => toast.success('Copied'),
                  () => toast.error('Could not copy. Select the text and copy manually.'),
                )
              }
            >
              <Copy />
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Download file"
              title="Download file"
              onClick={onDownload}
            >
              <Download />
            </Button>
          </div>
          {writable && (
            <Button
              ref={saveButton}
              variant="outline"
              size="icon-xs"
              aria-label="Save"
              title="Save (⌘/Ctrl S)"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              <Save />
            </Button>
          )}
        </div>
      </div>
      {saveError && (
        <p role="alert" className="border-b p-3 text-sm text-destructive">
          {saveError}
        </p>
      )}
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden" hidden={!source}>
        <CodeMirror
          className="h-full"
          value={content}
          height="100%"
          theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
          extensions={extensions}
          onCreateEditor={(view) => {
            view.scrollDOM.scrollTop = scroll.current.source;
          }}
          editable={writable && !saving}
          readOnly={!writable || saving}
          indentWithTab={false}
          onChange={(value) => {
            setDraft(value);
            setSaveError('');
          }}
        />
      </div>
      {!source &&
        (csv ? (
          <CsvPreview
            text={content}
            tabSeparated={/\.tsv$/i.test(node.name) || /tab-separated/.test(node.mime)}
          />
        ) : html ? (
          <iframe
            title={node.name}
            sandbox=""
            srcDoc={content}
            className="min-h-0 w-full flex-1 border-0 bg-background"
          />
        ) : (
          <article
            ref={preview}
            className="storage-markdown min-h-0 w-full min-w-0 flex-1 overflow-auto"
          >
            <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
          </article>
        ))}
      <AlertDialog
        open={blocker.status === 'blocked'}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave without saving?</AlertDialogTitle>
            <AlertDialogDescription>
              Your changes to {node.name} have not been saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={saving}
              onClick={() => {
                setTextSession(null);
                blocker.proceed?.();
              }}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
