import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useBackend } from '@/lib/backend';
import { useStorageBrowser } from './storage-context';
import { FileIcon } from './file-icon';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

export function StorageSearch() {
  const b = useStorageBrowser();
  const { actorId } = useBackend();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'text' | 'semantic'>('text');
  const [search, setSearch] = useState({ query: '', mode });
  const results = useInfiniteQuery({
    queryKey: ['storage-search', actorId, b.workspace.id, b.storage.id, search],
    queryFn: ({ pageParam }) => b.searchContent(b.storage.id, search.query, search.mode, pageParam),
    enabled: open && !!search.query,
    initialPageParam: '',
    getNextPageParam: (page) => page.nextPageToken || undefined,
    retry: false,
  });
  const items = results.data?.pages.flatMap((page) => page.hits) ?? [];
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Search file contents"
          title="Search file contents"
        >
          <Search />
        </Button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[85dvh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Search {b.storage.name}</DialogTitle>
          <DialogDescription>
            Find text and extracted artifacts throughout this storage.
          </DialogDescription>
        </DialogHeader>
        <Tabs value={mode} onValueChange={(value) => setMode(value as typeof mode)}>
          <TabsList>
            <TabsTrigger value="text">Exact text</TabsTrigger>
            <TabsTrigger value="semantic">Meaning</TabsTrigger>
          </TabsList>
        </Tabs>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch({ query: input.trim(), mode });
          }}
        >
          <Input
            aria-label="Search storage contents"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            maxLength={1000}
            placeholder={
              mode === 'text' ? 'Words or a phrase…' : 'Describe what you are looking for…'
            }
          />
          <Button disabled={!input.trim() || results.isFetching}>Search</Button>
        </form>
        {mode === 'semantic' && (
          <p className="text-xs text-muted-foreground">
            Searches files whose processing and indexing are complete.
          </p>
        )}
        <div className="min-h-0 overflow-y-auto">
          {results.error && (
            <div role="alert" className="py-3 text-sm text-destructive">
              <p>{results.error.message}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void results.refetch()}
              >
                Retry search
              </Button>
            </div>
          )}
          <ul className="divide-y">
            {items.map((hit, index) => (
              <li key={`${hit.node.id}:${hit.lineNumber ?? index}`}>
                <button
                  className="flex w-full gap-3 rounded-md px-2 py-3 text-left hover:bg-accent"
                  onClick={() => {
                    b.open(hit.node, hit.lineNumber);
                    setOpen(false);
                  }}
                >
                  <FileIcon node={hit.node} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{hit.node.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {hit.path}
                      {hit.lineNumber ? ` · Line ${hit.lineNumber}` : ''}
                    </span>
                    <span className="mt-1 line-clamp-3 block whitespace-pre-wrap text-sm">
                      {hit.snippet}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {!!search.query && !items.length && !results.error && (
            <p role="status" className="py-5 text-sm text-muted-foreground">
              {results.isFetching ? 'Searching…' : 'No matching files. Try another phrase.'}
            </p>
          )}
          {results.hasNextPage && (
            <Button
              variant="outline"
              disabled={results.isFetching}
              onClick={() => void results.fetchNextPage()}
            >
              Load more
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
