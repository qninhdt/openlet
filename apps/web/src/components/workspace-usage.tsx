import { useQuery } from '@tanstack/react-query';
import { HardDrive, AlertCircle, LoaderCircle } from 'lucide-react';
import { useBackend } from '@/lib/backend';
import { storageApi } from '@/lib/storage-api';
import { formatBytes } from '@/lib/storage-preview';
import { Button } from './ui/button';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';

export function WorkspaceUsage({ workspace }: { workspace: string }) {
  const { api, request, actorId } = useBackend();
  const quota = useQuery({
    queryKey: ['storage-quota', actorId, workspace],
    queryFn: () => storageApi(api!, workspace, request, actorId).quota(),
    refetchInterval: 30000,
  });
  const { used = 0, total = 0 } = quota.data ?? {};
  const percent = total > 0 ? Math.min(100, Math.floor((used / total) * 100)) : 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-lg"
          aria-label="Storage usage"
          className="relative rounded-full"
        >
          {quota.isPending ? (
            <LoaderCircle className="animate-spin" />
          ) : quota.error ? (
            <AlertCircle />
          ) : (
            <>
              <svg
                viewBox="0 0 34 34"
                className="pointer-events-none absolute size-8.5! -rotate-90"
                aria-hidden="true"
              >
                <circle
                  cx="17"
                  cy="17"
                  r="15.875"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.25"
                  className="text-foreground/10"
                />
                <circle
                  cx="17"
                  cy="17"
                  r="15.875"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.25"
                  pathLength="100"
                  strokeDasharray={`${percent} 100`}
                  strokeLinecap="round"
                  className={percent > 90 ? 'text-destructive' : 'text-muted-foreground'}
                />
              </svg>
              <HardDrive />
            </>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side="right"
        align="end"
        sideOffset={8}
        aria-label="Storage usage"
        className="w-72 max-w-[calc(100vw-4rem)] p-4"
      >
        <h2 className="mb-4 text-sm font-medium">Storage</h2>
        {quota.error ? (
          <div className="flex flex-col gap-3">
            <p role="alert" className="text-sm text-destructive">
              {quota.error.message}
            </p>
            <Button variant="outline" size="sm" onClick={() => void quota.refetch()}>
              Retry
            </Button>
          </div>
        ) : quota.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading storage…
          </p>
        ) : (
          <>
            <div className="mb-3 flex items-baseline justify-between gap-3 text-sm tabular-nums">
              <span>
                {formatBytes(used)} / {formatBytes(total)}
              </span>
              <span className="text-muted-foreground">{percent}%</span>
            </div>
            <dl className="flex items-center justify-between border-t pt-3 text-sm">
              <dt className="text-muted-foreground">Available</dt>
              <dd className="tabular-nums">{formatBytes(Math.max(0, total - used))}</dd>
            </dl>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
