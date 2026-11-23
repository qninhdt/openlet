import { useRef, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useAgentPreview } from './agent-preview';
import { StorageImage } from '@/components/storage/storage-image';
import { FileIcon } from '@/components/storage/file-icon';
import { Button } from '@/components/ui/button';
import { Attachment } from '@/components/ui/attachment';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
  type CarouselApi,
} from '@/components/ui/carousel';
import { cn } from '@/lib/utils';
import { downloadNodes, formatBytes, type StorageNode } from '@/lib/storage-preview';
import type { FileRef } from '@/lib/file-refs';
import { toast } from 'sonner';

function MessageFile({
  reference,
  node,
  pending,
  error,
  multiple,
  onPreview,
}: {
  reference: FileRef;
  node?: StorageNode;
  pending: boolean;
  error: boolean;
  multiple: boolean;
  onPreview: () => void;
}) {
  const p = useAgentPreview();
  const folder = (node?.kind ?? reference.kind) === 'folder';
  const image = !folder && (node?.mime ?? reference.mime ?? '').startsWith('image/');
  async function download() {
    if (!node) return;
    try {
      await downloadNodes({ nodes: [node] }, [node.id], () => {});
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not download file.');
    }
  }
  if (image)
    return (
      <button
        type="button"
        className={cn(
          'overflow-hidden rounded-xl bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring',
          multiple ? 'col-span-1 aspect-square' : 'col-span-2 aspect-4/3',
        )}
        aria-label={`Preview ${node?.name ?? reference.label}`}
        disabled={!node || error}
        onClick={onPreview}
      >
        {node ? (
          <StorageImage node={node} alt={node.name} className="block size-full" />
        ) : (
          <span className="p-3 text-caption text-muted-foreground">
            {error ? 'Image unavailable' : 'Loading image…'}
          </span>
        )}
      </button>
    );
  return (
    <Attachment
      state={error ? 'error' : pending ? 'processing' : 'done'}
      className="col-span-2 min-w-0 w-full"
    >
      <div className="flex min-w-0 w-full items-center gap-2 p-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          disabled={pending}
          onClick={() => void p.openFileReference(reference)}
        >
          <FileIcon
            node={
              node ?? {
                kind: folder ? 'folder' : 'file',
                name: reference.label,
                mime: reference.mime ?? '',
              }
            }
          />
          <span className="min-w-0">
            <span className="block truncate text-sm">{node?.name ?? reference.label}</span>
            <span className="block text-xs text-muted-foreground">
              {error
                ? folder
                  ? 'Folder unavailable'
                  : 'Unavailable · retry preview'
                : folder
                  ? 'Folder'
                  : node
                    ? formatBytes(node.size)
                    : 'Loading file…'}
            </span>
          </span>
        </button>
        {!folder && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Download ${node?.name ?? reference.label}`}
            disabled={!node || error}
            onClick={() => void download()}
          >
            <Download />
          </Button>
        )}
      </div>
    </Attachment>
  );
}

export function MessageFiles({ references }: { references?: FileRef[] }) {
  const p = useAgentPreview();
  const [selected, setSelected] = useState<string | null>(null);
  const [carousel, setCarousel] = useState<CarouselApi>();
  const trigger = useRef<HTMLElement | null>(null);
  const unique = (references ?? []).filter(
    (ref, index, all) =>
      all.findIndex(
        (other) => other.storage_id === ref.storage_id && other.node_id === ref.node_id,
      ) === index,
  );
  const files = useQueries({
    queries: unique.map((reference) => ({
      queryKey: [
        'storage-node',
        p.actorId,
        p.workspace.id,
        reference.storage_id,
        reference.node_id,
      ],
      queryFn: () => p.filesApi.stat(reference.storage_id, reference.node_id),
      staleTime: 30_000,
      retry: 1,
    })),
  });
  const images = files.flatMap((file) =>
    file.data?.mime.startsWith('image/') && !file.isError ? [file.data] : [],
  );
  const imageIndex = images.findIndex((node) => `${node.storage}/${node.id}` === selected);
  if (!unique.length) return null;
  return (
    <>
      <div className="grid w-80 max-w-full grid-cols-2 gap-1" aria-label="Attached files">
        {unique.map((ref, index) => (
          <MessageFile
            key={`${ref.storage_id}/${ref.node_id}`}
            reference={ref}
            node={files[index].data}
            pending={files[index].isPending}
            error={files[index].isError}
            multiple={unique.length > 1}
            onPreview={() => {
              trigger.current = document.activeElement as HTMLElement;
              setSelected(`${ref.storage_id}/${ref.node_id}`);
            }}
          />
        ))}
      </div>
      {imageIndex >= 0 && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setSelected(null);
          }}
        >
          <DialogContent
            aria-describedby={undefined}
            className="inset-0 h-dvh w-screen max-w-none translate-x-0 translate-y-0 gap-0 rounded-none border-0 p-0 sm:max-w-none"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              trigger.current?.focus();
            }}
            onKeyDown={(event) => {
              if (event.defaultPrevented) return;
              if (event.key === 'ArrowLeft') {
                event.preventDefault();
                carousel?.scrollPrev();
              }
              if (event.key === 'ArrowRight') {
                event.preventDefault();
                carousel?.scrollNext();
              }
            }}
          >
            <DialogTitle className="sr-only">Message photos</DialogTitle>
            <Carousel
              setApi={setCarousel}
              opts={{ startIndex: imageIndex }}
              aria-label="Message photos"
              className="h-full min-h-0 [&>[data-slot=carousel-content]]:h-full"
            >
              <CarouselContent className="ml-0 h-full">
                {images.map((node, index) => (
                  <CarouselItem
                    key={`${node.storage}/${node.id}`}
                    aria-label={`${index + 1} of ${images.length}`}
                    className="h-full px-12 py-14"
                  >
                    <StorageImage
                      node={node}
                      original
                      alt={node.name}
                      className="block size-full [&_img]:object-contain"
                    />
                  </CarouselItem>
                ))}
              </CarouselContent>
              {images.length > 1 && (
                <>
                  <CarouselPrevious aria-label="Previous image" className="left-3" />
                  <CarouselNext aria-label="Next image" className="right-3" />
                </>
              )}
            </Carousel>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
