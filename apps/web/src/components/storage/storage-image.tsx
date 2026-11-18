import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ImageOff } from 'lucide-react';
import { useBackend } from '@/lib/backend';
import { fileBlob, type StorageNode } from '@/lib/storage-preview';

export function StorageImage({
  node,
  className,
  alt = '',
  original = false,
}: {
  node: StorageNode;
  className?: string;
  alt?: string;
  original?: boolean;
}) {
  const { actorId } = useBackend();
  const element = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setVisible(true);
    });
    if (element.current) observer.observe(element.current);
    return () => observer.disconnect();
  }, []);
  const image = useQuery({
    queryKey: [
      original ? 'storage-image' : 'storage-thumbnail',
      actorId,
      node.storage,
      node.id,
      node.version,
      node.updated,
    ],
    enabled: visible,
    queryFn: () => (!original && node.thumbnail ? node.thumbnail() : fileBlob(node)),
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
    retry: 1,
  });
  useEffect(() => {
    setFailed(false);
    if (!image.data) {
      setUrl('');
      return;
    }
    const url = URL.createObjectURL(image.data);
    setUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image.data]);
  return (
    <span ref={element} className={className}>
      {image.error || failed ? (
        <span
          className="flex size-full items-center justify-center"
          title={image.error?.message ?? 'Image unavailable'}
        >
          <ImageOff className="size-5 text-muted-foreground" aria-label="Image unavailable" />
        </span>
      ) : url ? (
        <img
          src={url}
          alt={alt}
          className="size-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span role="status" aria-label="Loading image" className="block size-full bg-muted" />
      )}
    </span>
  );
}
