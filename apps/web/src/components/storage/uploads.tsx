import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { Check, LoaderCircle, RotateCcw, Upload, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { useBackend } from '@/lib/backend';
import { storageApi } from '@/lib/storage-api';
import { readUploads, type UploadResume } from '@/lib/upload-resume';
import { useQueryClient } from '@tanstack/react-query';

type Task = {
  id?: string;
  name: string;
  destination: string;
  run: (progress: (fraction: number) => void, signal: AbortSignal) => Promise<void>;
  onRemove?: () => void;
};
type Job = Task & {
  id: string;
  status: 'uploading' | 'done' | 'failed' | 'cancelled';
  progress: number;
  error?: string;
};
function createUploads() {
  const controllers = new Map<string, AbortController>();
  let jobs: Job[] = [];
  const listeners = new Set<() => void>();
  const publish = () => {
    for (const listener of listeners) listener();
  };
  const update = (id: string, patch: Partial<Job>) => {
    jobs = jobs.map((job) => (job.id === id ? { ...job, ...patch } : job));
    publish();
  };
  async function execute(id: string) {
    const job = jobs.find((job) => job.id === id);
    if (!job || controllers.has(id)) return;
    const controller = new AbortController();
    controllers.set(id, controller);
    update(id, { status: 'uploading', progress: 0, error: undefined });
    try {
      await job.run(
        (fraction) => update(id, { progress: Math.max(0, Math.min(1, fraction)) }),
        controller.signal,
      );
      update(id, { status: 'done', progress: 1 });
    } catch (error) {
      update(id, {
        status:
          error instanceof DOMException && error.name === 'AbortError' ? 'cancelled' : 'failed',
        error: error instanceof Error ? error.message : 'Upload failed. Retry this upload.',
      });
      if (controller.signal.aborted) job.onRemove?.();
    } finally {
      controllers.delete(id);
    }
  }
  return {
    snapshot: () => jobs,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    enqueue: async (task: Task) => {
      const id = task.id ?? crypto.randomUUID();
      jobs = [...jobs, { ...task, id, status: 'uploading', progress: 0 }];
      publish();
      await execute(id);
    },
    retry: execute,
    cancel: (id: string) => controllers.get(id)?.abort(),
    dispose: () => {
      for (const controller of controllers.values()) controller.abort('pause');
    },
    remove: (id: string) => {
      const job = jobs.find((job) => job.id === id);
      if (!job || job.status === 'uploading') return;
      job.onRemove?.();
      jobs = jobs.filter((job) => job.id !== id);
      publish();
    },
  };
}
const Context = createContext<ReturnType<typeof createUploads> | null>(null);
export function UploadsProvider({
  children,
  workspaceId,
}: {
  children: ReactNode;
  workspaceId: string;
}) {
  const [uploads] = useState(createUploads);
  useEffect(() => () => uploads.dispose(), [uploads]);
  return (
    <Context.Provider value={uploads}>
      {children}
      <UploadPanel workspaceId={workspaceId} />
    </Context.Provider>
  );
}
export function useUploads() {
  const uploads = useContext(Context);
  if (!uploads) throw new Error('UploadsProvider is missing');
  return uploads;
}
function UploadPanel({ workspaceId }: { workspaceId: string }) {
  const backend = useBackend();
  const client = useQueryClient();
  const [recovery, setRecovery] = useState(() =>
    readUploads(backend.actorId).filter((item) => item.workspace === workspaceId),
  );
  const uploads = useUploads();
  const jobs = useSyncExternalStore(uploads.subscribe, uploads.snapshot);
  if (!jobs.length && !recovery.length) return null;
  const files = storageApi(backend.api!, workspaceId, backend.request, backend.actorId);
  const active = jobs.filter((job) => job.status === 'uploading').length;
  return (
    <section
      aria-label="Uploads"
      className="fixed right-4 bottom-20 z-50 w-80 max-w-[calc(100vw-32px)] overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg"
    >
      <header className="flex items-center gap-2 px-3 py-2">
        <Upload className="size-4 text-muted-foreground" />
        <span className="flex-1 text-sm">{active ? `Uploading ${active}` : 'Uploads'}</span>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="Dismiss uploads"
          onClick={() => {
            for (const job of jobs) uploads.remove(job.id);
          }}
        >
          <X />
        </Button>
      </header>
      <div className="max-h-64 overflow-auto border-t">
        {jobs.map((job) => (
          <div
            key={job.id}
            className="flex items-start gap-2 px-3 py-3"
            data-upload-status={job.status}
          >
            <div className="mt-0.5 shrink-0 text-muted-foreground">
              {job.status === 'uploading' ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : job.status === 'done' ? (
                <Check className="size-4" />
              ) : (
                <Upload className="size-4 text-destructive" />
              )}
            </div>
            <div className="min-w-0 flex-1 text-caption">
              <p className="truncate" title={job.name}>
                {job.name}
              </p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {job.status === 'failed'
                  ? job.error
                  : job.status === 'cancelled'
                    ? 'Cancelled'
                    : job.status === 'done'
                      ? `Uploaded · ${job.destination}`
                      : job.destination}
              </p>
              {job.status === 'uploading' && (
                <Progress
                  aria-label={`Upload ${job.name}`}
                  value={job.progress * 100}
                  className="mt-2 h-1"
                />
              )}
            </div>
            {job.status === 'uploading' && (
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Cancel ${job.name}`}
                onClick={() => uploads.cancel(job.id)}
              >
                <X />
              </Button>
            )}
            {(job.status === 'failed' || job.status === 'cancelled') && (
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Retry ${job.name}`}
                onClick={() => void uploads.retry(job.id)}
              >
                <RotateCcw />
              </Button>
            )}
          </div>
        ))}
        {recovery.map((saved) => (
          <UploadRecovery
            key={saved.requestId}
            saved={saved}
            files={files}
            onRemove={() =>
              setRecovery((items) => items.filter((item) => item.requestId !== saved.requestId))
            }
            onResume={(file) => {
              setRecovery((items) => items.filter((item) => item.requestId !== saved.requestId));
              void uploads.enqueue({
                name: saved.name,
                destination: 'Files',
                run: async (progress, signal) => {
                  await files.resumeUpload(
                    saved,
                    file,
                    (loaded, total) => progress(total ? loaded / total : 1),
                    signal,
                  );
                  await client.invalidateQueries({ queryKey: ['storage-folder'] });
                  await client.invalidateQueries({ queryKey: ['storage-quota'] });
                },
              });
            }}
          />
        ))}
      </div>
    </section>
  );
}

function UploadRecovery({
  saved,
  files,
  onResume,
  onRemove,
}: {
  saved: UploadResume;
  files: ReturnType<typeof storageApi>;
  onResume: (file: File) => void;
  onRemove: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  return (
    <div className="border-t px-3 py-3 text-sm">
      <p className="truncate">{saved.name}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Interrupted upload. Select the original file to resume into Files.
      </p>
      <input
        ref={input}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Original file for ${saved.name}`}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) onResume(file);
        }}
      />
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={pending}
          onClick={() => input.current?.click()}
        >
          Resume upload
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={pending}
          onClick={() => {
            setPending(true);
            setError('');
            void files
              .cancelUpload(saved)
              .then(onRemove)
              .catch((error) =>
                setError(
                  error instanceof Error ? error.message : 'Could not cancel upload. Try again.',
                ),
              )
              .finally(() => setPending(false));
          }}
        >
          {pending ? 'Cancelling…' : 'Cancel upload'}
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
