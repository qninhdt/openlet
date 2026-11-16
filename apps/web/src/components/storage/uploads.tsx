import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Check, LoaderCircle, RotateCcw, Upload, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';

type Task = {
  id?: string;
  name: string;
  destination: string;
  run: (progress: (fraction: number) => void) => Promise<void>;
  onRemove?: () => void;
};
type Job = Task & {
  id: string;
  status: 'uploading' | 'done' | 'failed';
  progress: number;
  error?: string;
};
function createUploads() {
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
    if (!job) return;
    update(id, { status: 'uploading', progress: 0, error: undefined });
    try {
      await job.run((fraction) => update(id, { progress: Math.max(0, Math.min(1, fraction)) }));
      update(id, { status: 'done', progress: 1 });
    } catch (error) {
      update(id, {
        status: 'failed',
        error: error instanceof Error ? error.message : 'Upload failed. Retry this upload.',
      });
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
export function UploadsProvider({ children }: { children: ReactNode }) {
  const [uploads] = useState(createUploads);
  return (
    <Context.Provider value={uploads}>
      {children}
      <UploadPanel />
    </Context.Provider>
  );
}
export function useUploads() {
  const uploads = useContext(Context);
  if (!uploads) throw new Error('UploadsProvider is missing');
  return uploads;
}
function UploadPanel() {
  const uploads = useUploads();
  const jobs = useSyncExternalStore(uploads.subscribe, uploads.snapshot);
  if (!jobs.length) return null;
  const active = jobs.filter((job) => job.status === 'uploading').length;
  return (
    <section
      aria-label="Uploads"
      className="fixed right-4 bottom-20 z-50 w-80 max-w-[calc(100vw-32px)] overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg min-[722px]:bottom-4"
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
            {job.status === 'failed' && (
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
      </div>
    </section>
  );
}
