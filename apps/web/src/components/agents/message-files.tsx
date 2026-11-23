import { useEffect, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { Download, ImageOff } from 'lucide-react';
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

type AttachmentFile = {
  reference: FileRef;
  node?: StorageNode;
  pending: boolean;
  error: boolean;
};

function MessageFile({ reference, node, pending, error }: AttachmentFile) {
  const p = useAgentPreview();
  const folder = (node?.kind ?? reference.kind) === 'folder';
  async function download() {
    if (!node) return;
    try {
      await downloadNodes({ nodes: [node] }, [node.id], () => {});
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not download file.');
    }
  }
  return (
    <Attachment
      state={error ? 'error' : pending ? 'processing' : 'done'}
      className="w-80 min-w-0 max-w-full"
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

function photoName(photo: AttachmentFile) {
  return photo.node?.name ?? photo.reference.label;
}

function MessagePhoto({
  photo,
  className,
  original,
}: {
  photo: AttachmentFile;
  className: string;
  original?: boolean;
}) {
  if (photo.error)
    return (
      <span className={cn(className, 'grid place-items-center text-muted-foreground')}>
        <ImageOff className="size-5" aria-label="Image unavailable" role="img" />
      </span>
    );
  if (!photo.node) return <span role="status" aria-label="Loading image" className={className} />;
  return (
    <StorageImage
      node={photo.node}
      alt={photoName(photo)}
      className={className}
      original={original}
    />
  );
}

function PhotoGallery({
  photos,
  startIndex,
  trigger,
  onClose,
}: {
  photos: AttachmentFile[];
  startIndex: number;
  trigger: HTMLButtonElement;
  onClose: () => void;
}) {
  const [carousel, setCarousel] = useState<CarouselApi>();
  const [activeIndex, setActiveIndex] = useState(startIndex);
  useEffect(() => {
    if (!carousel) return;
    const select = () => setActiveIndex(carousel.selectedScrollSnap());
    carousel.on('select', select).on('reInit', select);
    return () => {
      carousel.off('select', select).off('reInit', select);
    };
  }, [carousel]);
  const multiple = photos.length > 1;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        aria-describedby={undefined}
        className="inset-0 h-dvh w-screen max-w-none translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)] gap-0 rounded-none border-0 bg-background p-0 sm:max-w-none"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.focus();
        }}
        onKeyDown={(event) => {
          if (event.defaultPrevented) return;
          if (event.key === 'ArrowLeft') carousel?.scrollPrev();
          if (event.key === 'ArrowRight') carousel?.scrollNext();
        }}
      >
        <DialogTitle className="sr-only">Message photos</DialogTitle>
        <p className="min-h-12 truncate py-3.5 pr-14 pl-4 font-medium">
          {photoName(photos[activeIndex] ?? photos[startIndex])}
        </p>
        <Carousel
          setApi={setCarousel}
          opts={{ startIndex }}
          aria-label="Message photos"
          className="h-full min-h-0 [&>[data-slot=carousel-content]]:h-full"
        >
          <CarouselContent className="ml-0 h-full touch-pan-y">
            {photos.map((photo, index) => (
              <CarouselItem
                key={`${photo.reference.storage_id}/${photo.reference.node_id}`}
                aria-label={`${index + 1} of ${photos.length}`}
                aria-hidden={index !== activeIndex}
                className={cn('h-full px-3 pt-0 pb-3', multiple && 'pb-14')}
              >
                <MessagePhoto
                  photo={photo}
                  original
                  className="block size-full [&_img]:object-contain"
                />
              </CarouselItem>
            ))}
          </CarouselContent>
          {multiple && (
            <div className="absolute inset-x-0 bottom-2 flex items-center justify-center gap-3">
              <CarouselPrevious
                aria-label="Previous image"
                className="static size-10 translate-y-0"
              />
              <span aria-live="polite" className="min-w-12 text-center text-xs tabular-nums">
                {activeIndex + 1} / {photos.length}
              </span>
              <CarouselNext aria-label="Next image" className="static size-10 translate-y-0" />
            </div>
          )}
        </Carousel>
      </DialogContent>
    </Dialog>
  );
}

const albumLimit = 6;

function MessagePhotos({ photos }: { photos: AttachmentFile[] }) {
  const [opened, setOpened] = useState<{ index: number; trigger: HTMLButtonElement }>();
  const single = photos.length === 1;
  const visible = photos.slice(0, albumLimit);
  const remaining = photos.length - visible.length;
  return (
    <>
      <div
        className={cn(
          'min-w-0 max-w-full',
          single
            ? 'w-fit max-w-[min(100%,24rem)]'
            : 'grid w-lg grid-cols-6 gap-0.5 overflow-hidden rounded-xl',
        )}
        role="group"
        aria-label={single ? 'Photo attachment' : 'Photo album'}
      >
        {visible.map((photo, index) => {
          const name = photoName(photo);
          const more = remaining > 0 && index === albumLimit - 1;
          const half =
            visible.length === 2 || visible.length === 4 || (visible.length === 5 && index < 2);
          return (
            <button
              key={`${photo.reference.storage_id}/${photo.reference.node_id}`}
              type="button"
              className={cn(
                'relative block min-w-0 overflow-hidden bg-muted outline-none focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                single ? 'rounded-xl' : 'aspect-[4/3] max-h-40 w-full',
                !single && (half ? 'col-span-3' : 'col-span-2'),
              )}
              aria-label={more ? `View ${remaining} more photos` : `Preview ${name}`}
              onClick={(event) =>
                setOpened({ index: more ? albumLimit : index, trigger: event.currentTarget })
              }
            >
              <MessagePhoto
                photo={photo}
                className={
                  single
                    ? 'block max-w-full [&:not(:has(img))]:h-32 [&:not(:has(img))]:w-56 [&_img]:h-auto [&_img]:max-h-80 [&_img]:w-auto [&_img]:max-w-full'
                    : 'block size-full [&_img]:object-contain'
                }
              />
              {more && (
                <span
                  aria-hidden="true"
                  className="absolute inset-0 grid place-items-center bg-black/65 text-base font-semibold text-white"
                >
                  +{remaining}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {opened && photos[opened.index] && (
        <PhotoGallery
          photos={photos}
          startIndex={opened.index}
          trigger={opened.trigger}
          onClose={() => setOpened(undefined)}
        />
      )}
    </>
  );
}

export function MessageFiles({ references }: { references?: FileRef[] }) {
  const p = useAgentPreview();
  const seen = new Set<string>();
  const unique = (references ?? []).filter((ref) => {
    const key = `${ref.storage_id}/${ref.node_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
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
  if (!unique.length) return null;
  const photos: AttachmentFile[] = [];
  const documents: AttachmentFile[] = [];
  unique.forEach((reference, index) => {
    const { data: node, isPending: pending, isError: error } = files[index];
    const image =
      (node?.kind ?? reference.kind) !== 'folder' &&
      (node?.mime ?? reference.mime ?? '').startsWith('image/');
    (image ? photos : documents).push({ reference, node, pending, error });
  });
  return (
    <div
      role="group"
      aria-label="Attached files"
      className="flex min-w-0 max-w-full flex-col gap-1"
    >
      {photos.length > 0 && <MessagePhotos photos={photos} />}
      {documents.map((file) => (
        <MessageFile key={`${file.reference.storage_id}/${file.reference.node_id}`} {...file} />
      ))}
    </div>
  );
}
