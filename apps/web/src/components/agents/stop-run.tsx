import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Square } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useAgentPreview } from './agent-preview';

export function StopRun({
  agent,
  run,
  compact = false,
}: {
  agent: string;
  run: string | null | undefined;
  compact?: boolean;
}) {
  const p = useAgentPreview();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  if (!p.capabilities.can_edit_settings || !run) return null;
  return (
    <Button
      variant="outline"
      size={compact ? 'icon-sm' : 'sm'}
      aria-label={busy ? 'Stopping agent' : 'Stop agent'}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await p.live.api!(p.live.path + `/agents/${agent}/cancel`, {
            method: 'POST',
            body: JSON.stringify({ run_id: run }),
          });
          await Promise.all([
            p.live.refresh(),
            client.invalidateQueries({ queryKey: ['box-graph', p.actorId, p.workspace.id] }),
          ]);
        } catch (error) {
          toast.error(error instanceof Error ? error.message : 'Could not stop this run.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <Square />
      {!compact && (busy ? 'Stopping…' : 'Stop agent')}
    </Button>
  );
}
