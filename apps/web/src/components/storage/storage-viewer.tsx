import { useEffect, useRef, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileQuestion,
  Maximize,
  Minus,
  Plus,
  X,
} from 'lucide-react';
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
  return (
    <FileViewer
      node={node}
      images={b.visible.filter((file) => file.mime.startsWith('image/'))}
      onOpen={b.open}
      onClose={b.closeFile}
      onDownload={() => void b.download([node.id])}
      textAccess={{
        writable: b.roots.some((root) => root.id === node.storage && root.write),
        saveText: b.saveText,
        getTextSession: b.getTextSession,
        setTextSession: b.setTextSession,
      }}
    />
  );
}

export function FileViewer({
  node,
  images = [],
  onOpen,
  onClose,
  onDownload,
  textAccess,
  embedded = false,
  active = true,
}: {
  node: StorageNode;
  images?: StorageNode[];
  onOpen?: (node: StorageNode) => void;
  onClose: () => void;
  onDownload: () => void;
  textAccess: TextFileAccess;
  embedded?: boolean;
  active?: boolean;
}) {
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
  const text =
    !spreadsheet &&
    (/^text\//.test(node.mime) ||
      /^application\/(json|javascript|xml)$/.test(node.mime) ||
      /\.(md|mdx|markdown|txt|py|js|jsx|ts|tsx|go|rs|css|scss|yaml|yml|toml|log|json|csv|tsv|html|xml|sh|sql|ini|conf)$/i.test(
        node.name,
      ));
  const index = images.findIndex((file) => file.id === node.id);
  function adjacent(delta: number) {
    const next = images[index + delta];
    if (next) onOpen?.(next);
  }
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
  }, [node.id, node.blob, node.url, spreadsheet, text]);
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
      if (image && event.key === 'ArrowLeft') adjacent(-1);
      if (image && event.key === 'ArrowRight') adjacent(1);
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
  }, [onClose, onOpen, images, embedded, active, image, index]);
  const current = resource?.id === node.id ? resource : undefined;
  return (
    <section
      role={embedded ? 'region' : 'dialog'}
      aria-modal={embedded ? undefined : true}
      aria-label={`Preview ${node.name}`}
      className={
        embedded
          ? 'storage-viewer relative flex h-full min-h-0 min-w-0 flex-col bg-sidebar'
          : 'storage-viewer absolute inset-0 z-10 flex flex-col bg-sidebar'
      }
    >
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
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium">{node.name}</h2>
        <div className="flex shrink-0 gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Download file" onClick={onDownload}>
            <Download />
          </Button>
        </div>
      </div>
      <div className="storage-viewer-body min-h-0 flex-1 overflow-auto">
        {text ? (
          <TextFile key={node.id} node={node} {...textAccess} />
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
                className="max-h-[calc(100%-32px)] max-w-[calc(100%-72px)] object-contain select-none"
                alt={node.name}
                draggable={false}
                style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
                onDoubleClick={() => {
                  setZoom(zoom === 1 ? 2 : 1);
                  setPan({ x: 0, y: 0 });
                }}
              />
              <Button
                className="storage-image-prev absolute top-1/2 left-3 -translate-y-1/2"
                variant="secondary"
                size="icon"
                aria-label="Previous image"
                disabled={index <= 0}
                onClick={() => adjacent(-1)}
              >
                <ChevronLeft />
              </Button>
              <Button
                className="storage-image-next absolute top-1/2 right-3 -translate-y-1/2"
                variant="secondary"
                size="icon"
                aria-label="Next image"
                disabled={index < 0 || index >= images.length - 1}
                onClick={() => adjacent(1)}
              >
                <ChevronRight />
              </Button>
            </div>
            <div className="storage-zoom flex items-center gap-1 self-center p-1">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Zoom out"
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
            <div className="storage-image-strip flex shrink-0 justify-center gap-1.5 overflow-auto px-3 pt-2 pb-4">
              {images.map((item) => (
                <ImageThumb
                  key={item.id}
                  node={item}
                  active={item.id === node.id}
                  onClick={() => onOpen?.(item)}
                />
              ))}
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
function ImageThumb({
  node,
  active,
  onClick,
}: {
  node: StorageNode;
  active: boolean;
  onClick: () => void;
}) {
  const [url, setUrl] = useState(node.url);
  useEffect(() => {
    if (!node.blob) return;
    const url = URL.createObjectURL(node.blob);
    setUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [node.blob]);
  return (
    <button
      className="h-11 w-14 shrink-0 overflow-hidden rounded-sm border-2 border-transparent opacity-60 aria-pressed:border-ring aria-pressed:opacity-100"
      aria-label={`View ${node.name}`}
      aria-pressed={active}
      onClick={onClick}
    >
      <img src={url} alt="" className="size-full object-cover" />
    </button>
  );
}
