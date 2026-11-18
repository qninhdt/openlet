import { useEffect } from 'react';
import { useAgentPreview } from './agent-preview';
import { StorageProvider } from '@/components/storage/storage-context';
import { StoragePage } from '@/components/storage/storage-page';
import { Button } from '@/components/ui/button';

export function ConversationStorage() {
  const p = useAgentPreview();
  useEffect(() => {
    void p.ensureConversation().catch(() => {});
  }, [p.resource.id]);
  const storage = p.conversation.data;
  if (!storage)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-sm text-muted-foreground">
        <p role={p.conversation.error ? 'alert' : 'status'}>
          {p.conversation.error?.message ?? 'Loading storage…'}
        </p>
        {p.conversation.error && (
          <Button variant="outline" onClick={() => void p.ensureConversation().catch(() => {})}>
            Retry
          </Button>
        )}
      </div>
    );
  return (
    <StorageProvider
      key={storage.storage_id}
      workspace={p.workspace}
      root={{ id: storage.storage_id, name: 'Files', root: storage.root_node_id, write: true }}
      onAttachFiles={(nodes) => {
        void (async () => {
          for (const node of nodes) await p.attachFile(node);
        })();
      }}
      onOpenFile={(node, line) =>
        void p.openFileReference(
          { storage_id: node.storage, node_id: node.id, label: node.name },
          line,
        )
      }
    >
      <StoragePage embedded />
    </StorageProvider>
  );
}
