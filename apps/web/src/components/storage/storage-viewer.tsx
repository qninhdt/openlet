import { isTextFile } from '@/lib/file-types';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';
import { useBackend } from '@/lib/backend';
import { storageApi } from '@/lib/storage-api';
import { formatBytes, uniqueName } from '@/lib/storage-preview';
import { FileProcessing } from './file-processing';
import { Download, FileQuestion, Maximize, Minus, Plus, X } from 'lucide-react';
import { TextFile, type TextFileAccess } from './storage-text-file';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { parseSpreadsheet } from '@/vendor/openbot/spreadsheet-workbook';
import { fileBlob, useStorageBrowser, type StorageNode } from './storage-context';

function Spreadsheet({ bytes }: { bytes: Uint8Array }) {
  const [sheet, setSheet] = useState(0);
  const [workbook, setWorkbook] = useState<ReturnType<typeof parseSpreadsheet>>();
  const [error, setError] = useState('');
  useEffect(() => {
    try {
      setWorkbook(parseSpreadsheet(bytes));
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not read workbook.');
    }
  }, [bytes]);
  if (error)
    return (
      <p role="alert" className="p-6 text-sm text-muted-foreground">
        {error}
      </p>
    );
  const current = workbook?.sheets[sheet];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Tabs value={String(sheet)} onValueChange={(value) => setSheet(Number(value))}>
        <TabsList variant="line">
          {workbook?.sheets.map((item, index) => (
            <TabsTrigger key={index} value={String(index)}>
              {item.name}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="storage-sheet border-collapse text-caption whitespace-nowrap">
          <tbody>
            {current?.rows.map((row, i) => (
              <tr key={i}>
                <th className="border bg-muted px-3 py-1.5 text-left font-normal text-muted-foreground">
                  {i + 1}
                </th>
                {row.map((value, j) => (
                  <td key={j} className="border px-3 py-1.5 text-left">
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {workbook?.truncated && (
          <p className="p-3 text-sm text-muted-foreground">
            Preview is limited to the first 500 rows and 50 columns. Download for the full workbook.
          </p>
        )}
      </div>
    </div>
  );
}
export function StorageViewer({ node }: { node: StorageNode }) {
  const b = useStorageBrowser();
  const getTextSession = useCallback(() => b.getTextSession(node.id), [b.getTextSession, node.id]);
  const setTextSession = useCallback(
    (session: import('./storage-context').StorageTextSession | null) =>
      b.setTextSession(node.id, session),
    [b.setTextSession, node.id],
  );
  return (
    <FileViewer
      embedded
      active={b.file?.id === node.id}
      node={node}
      focusLine={b.lineTarget?.id === node.id ? b.lineTarget : undefined}
      onClose={() => b.closeFile(node.id)}
      onDownload={() => void b.download([node.id])}
      textAccess={{
        writable: b.roots.some((root) => root.id === node.storage && root.write),
        saveText: b.saveText,
        getTextSession,
        setTextSession,
      }}
    />
  );
}

export function FileViewer({
  node: initialNode,
  focusLine,
  onClose,
  onDownload,
  textAccess,
  embedded = false,
  active = true,
}: {
  node: StorageNode;
  focusLine?: { line: number; request: string };
  onClose: () => void;
  onDownload: () => void;
  textAccess: TextFileAccess;
  embedded?: boolean;
  active?: boolean;
}) {
  const backend = useBackend();
  const { workspaceId = '' } = useParams({ strict: false });
  const client = useQueryClient();
  const files = useMemo(
    () => storageApi(backend.api!, workspaceId, backend.request, backend.actorId),
    [backend.api, backend.request, backend.actorId, workspaceId],
  );
  const statKey = [
    'storage-node',
    backend.actorId,
    workspaceId,
    initialNode.storage,
    initialNode.id,
  ];
  const stat = useQuery({
    queryKey: statKey,
    queryFn: () => files.stat(initialNode.storage, initialNode.id),
    enabled: active && backend.ready && !!backend.api,
    placeholderData: initialNode,
    refetchInterval: active ? 5_000 : false,
    retry: 1,
  });
  const node = stat.data ?? initialNode;
  const [resource, setResource] = useState<{
    id: string;
    url: string;
    bytes?: Uint8Array;
  }>();
  const [error, setError] = useState('');
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const close = useRef<HTMLButtonElement>(null);
  const image = node.mime.startsWith('image/');
  const spreadsheet = /\.xlsx$/i.test(node.name);
  const text = !spreadsheet && !image && isTextFile(node.name, node.mime);
  useEffect(() => {
    if (embedded) return;
    const origin = document.activeElement as HTMLElement;
    close.current?.focus();
    return () => {
      if (origin?.isConnected) origin.focus();
    };
  }, [embedded]);
  useEffect(() => {
    if (text) return;
    let alive = true;
    let url = '';
    setError('');
    setResource(undefined);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    void fileBlob(node)
      .then(async (blob) => {
        if (!alive) return;
        url = URL.createObjectURL(blob);
        if (spreadsheet && blob.size > 8 * 1024 * 1024)
          throw new Error(
            'This workbook is too large to preview. Download it to open the full file.',
          );
        const bytes = spreadsheet ? new Uint8Array(await blob.arrayBuffer()) : undefined;
        if (alive)
          setResource({
            id: node.id,
            url,
            bytes,
          });
      })
      .catch(
        (error) =>
          alive && setError(error instanceof Error ? error.message : 'Could not load this file.'),
      );
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [node.id, node.version, node.updated, node.blob, node.url, spreadsheet, text]);
  useEffect(() => {
    if (!active) return;
    function key(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        (event.target as HTMLElement).closest('[role=menu],[role=listbox],[role=alertdialog]')
      )
        return;
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
      if ((event.target as HTMLElement).closest('input,textarea,[contenteditable]')) return;
      if (!embedded && event.key === 'Tab') {
        const elements = Array.from(
          document.querySelectorAll<HTMLElement>(
            '.storage-viewer button:not(:disabled),.storage-viewer [tabindex="0"],.storage-viewer iframe',
          ),
        );
        const at = elements.indexOf(document.activeElement as HTMLElement);
        if (event.shiftKey && at === 0) {
          event.preventDefault();
          elements.at(-1)?.focus();
        } else if (!event.shiftKey && at === elements.length - 1) {
          event.preventDefault();
          elements[0]?.focus();
        }
      }
    }
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose, embedded, active]);
  const current = resource?.id === node.id ? resource : undefined;
  const processing = node.processing ? (
    <FileProcessing
      key={`${node.id}:${node.version}`}
      node={node}
      files={files}
      writable={textAccess.writable && !node.readonly && !stat.isError}
      onUpdated={(value) => client.setQueryData(statKey, value)}
    />
  ) : null;
  return (
    <section
      role={embedded ? 'region' : 'dialog'}
      aria-modal={embedded ? undefined : true}
      aria-label={`Preview ${node.name}`}
      className={
        embedded
          ? 'storage-viewer @container/file-viewer relative flex h-full min-h-0 min-w-0 flex-col bg-sidebar'
          : 'storage-viewer @container/file-viewer absolute inset-0 z-10 flex flex-col bg-sidebar'
      }
    >
      {stat.error && (
        <p role="alert" className="border-b p-3 text-sm text-destructive">
          {stat.error.message} Your unsaved draft is retained.{' '}
          <Button size="sm" variant="outline" onClick={() => void stat.refetch()}>
            Retry
          </Button>
        </p>
      )}
      {!text && (
        <div className="storage-viewer-head flex min-h-11 items-center gap-2 border-b px-3 py-1">
          {!embedded && (
            <Button
              ref={close}
              variant="ghost"
              size="icon-sm"
              aria-label="Close preview"
              onClick={onClose}
            >
              <X />
            </Button>
          )}
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            {embedded ? formatBytes(node.size) : node.name}
          </span>
          {image && (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Zoom out"
                disabled={zoom <= 0.25}
                onClick={() => setZoom((value) => Math.max(0.25, value - 0.25))}
              >
                <Minus />
              </Button>
              <span className="w-12 text-center text-xs tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Zoom in"
                disabled={zoom >= 5}
                onClick={() => setZoom((value) => Math.min(5, value + 0.25))}
              >
                <Plus />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Fit image"
                onClick={() => {
                  setZoom(1);
                  setPan({ x: 0, y: 0 });
                }}
              >
                <Maximize />
              </Button>
            </div>
          )}
          {processing}
          <div className="flex shrink-0 gap-1">
            <Button variant="ghost" size="icon-sm" aria-label="Download file" onClick={onDownload}>
              <Download />
            </Button>
          </div>
        </div>
      )}
      <div className="storage-viewer-body min-h-0 flex-1 overflow-auto">
        {text ? (
          <TextFile
            key={node.id}
            node={node}
            focusLine={focusLine}
            onDownload={onDownload}
            toolbarEnd={processing}
            active={active}
            {...textAccess}
            writable={textAccess.writable && !node.readonly && !stat.isError}
            refreshNode={async () => {
              const latest = await files.stat(node.storage, node.id);
              client.setQueryData(statKey, latest);
              return latest;
            }}
            saveText={async (current, content) => {
              const saved = await textAccess.saveText(current, content);
              client.setQueryData(statKey, saved);
              return saved;
            }}
            saveCopy={async (current, content) => {
              const latest = await files.stat(current.storage, current.id);
              const siblings = await files.list(latest.storage, latest.parent);
              const name = uniqueName(current.name, siblings, latest.parent);
              const copy = await files.create(latest.storage, latest.parent, name, {
                content,
                mediaType: current.mime,
              });
              await client.invalidateQueries({ queryKey: ['storage-folder'] });
              await client.invalidateQueries({ queryKey: ['storage-quota'] });
              return copy;
            }}
          />
        ) : error ? (
          <div className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <FileQuestion className="mb-4 size-9" />
            <p role="alert">{error}</p>
            <Button className="mt-4" variant="outline" onClick={onDownload}>
              <Download />
              Download file
            </Button>
          </div>
        ) : !current ? (
          <p
            className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground"
            role="status"
          >
            Loading preview…
          </p>
        ) : image ? (
          <div className="storage-lightbox flex h-full min-h-0 flex-col">
            <div
              className="storage-image-stage relative flex min-h-0 flex-1 touch-none items-center justify-center overflow-hidden cursor-grab active:cursor-grabbing"
              onWheel={(event) => {
                setZoom((value) =>
                  Math.max(0.25, Math.min(5, value + (event.deltaY < 0 ? 0.15 : -0.15))),
                );
              }}
              onPointerDown={(event) => {
                if ((event.target as HTMLElement).closest('button')) return;
                const element = event.currentTarget;
                element.setPointerCapture(event.pointerId);
                const initial = { x: event.clientX, y: event.clientY, pan };
                const move = (e: globalThis.PointerEvent) =>
                  setPan({
                    x: initial.pan.x + e.clientX - initial.x,
                    y: initial.pan.y + e.clientY - initial.y,
                  });
                const stop = () => {
                  element.removeEventListener('pointermove', move);
                  element.removeEventListener('pointerup', stop);
                  element.removeEventListener('pointercancel', stop);
                };
                element.addEventListener('pointermove', move);
                element.addEventListener('pointerup', stop);
                element.addEventListener('pointercancel', stop);
              }}
            >
              <img
                src={current.url}
                className="max-h-[calc(100%-32px)] max-w-[calc(100%-32px)] object-contain select-none"
                alt={node.name}
                onError={() =>
                  setError(
                    'This image could not be displayed. Download it to open the original file.',
                  )
                }
                draggable={false}
                style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
                onDoubleClick={() => {
                  setZoom(zoom === 1 ? 2 : 1);
                  setPan({ x: 0, y: 0 });
                }}
              />
            </div>
          </div>
        ) : spreadsheet && current.bytes ? (
          <Spreadsheet bytes={current.bytes} />
        ) : node.mime === 'application/pdf' ? (
          <iframe title={node.name} src={current.url} className="size-full border-0" />
        ) : node.mime.startsWith('audio/') ? (
          <div className="storage-media flex h-full items-center justify-center p-6">
            <audio controls src={current.url} className="w-full max-w-120" />
          </div>
        ) : node.mime.startsWith('video/') ? (
          <div className="storage-media flex h-full items-center justify-center p-6">
            <video controls src={current.url} className="max-h-full max-w-full" />
          </div>
        ) : (
          <div className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <FileQuestion className="mb-3 size-10" strokeWidth={1.25} />
            <p className="font-medium text-foreground">No preview available</p>
            <p className="mt-1 text-sm">Download this file to open it on your device.</p>
            <Button className="mt-4" variant="outline" onClick={onDownload}>
              <Download />
              Download file
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
