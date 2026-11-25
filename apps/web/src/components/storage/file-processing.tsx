import { useRef, useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { storageApi } from '@/lib/storage-api';
import type { StorageNode } from '@/lib/storage-preview';

const stages: Record<string, string> = {
  queued: 'Queued for processing…',
  parsed: 'Enriching extracted content…',
  enriched: 'Indexing file content…',
  ready: 'File processing complete',
};

export function FileProcessing({
  node,
  files,
  writable,
  onUpdated,
}: {
  node: StorageNode;
  files: ReturnType<typeof storageApi>;
  writable: boolean;
  onUpdated: (node: StorageNode) => void;
}) {
  const requestId = useRef(crypto.randomUUID());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const processing = node.processing!;
  const status = processing.errorCode
    ? `File processing failed (${processing.errorCode}).`
    : (stages[processing.stage] ?? 'Processing file…');
  async function retry() {
    setPending(true);
    setError('');
    try {
      onUpdated(await files.retryProcessing(node, requestId.current));
      requestId.current = crypto.randomUUID();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not restart processing. Try again.');
    } finally {
      setPending(false);
    }
  }
  return (
    <Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={status}>
              <span
                aria-hidden="true"
                className={cn(
                  'size-2 rounded-full',
                  processing.errorCode
                    ? 'bg-destructive'
                    : processing.stage === 'ready'
                      ? 'bg-emerald-600 dark:bg-emerald-400'
                      : 'bg-amber-500 dark:bg-amber-400',
                )}
              />
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{status}</TooltipContent>
      </Tooltip>
      <PopoverContent align="end">
        <p role="status">{status}</p>
        {processing.errorCode && processing.stage !== 'ready' && writable && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => void retry()}>
            <RotateCcw />
            {pending ? 'Restarting…' : 'Retry processing'}
          </Button>
        )}
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
