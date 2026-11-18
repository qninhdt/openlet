import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useBlocker } from '@tanstack/react-router';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import type { StorageTextSession } from './storage-context';

const Context = createContext<Map<string, StorageTextSession> | null>(null);
export function FileSessionsProvider({ children }: { children: ReactNode }) {
  const sessions = useMemo(() => new Map<string, StorageTextSession>(), []);
  const hasDrafts = () =>
    [...sessions.values()].some(
      (session) => session.draft !== undefined && session.draft !== session.text,
    );
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => {
      const from = 'workspaceId' in current.params ? current.params.workspaceId : undefined;
      const to = 'workspaceId' in next.params ? next.params.workspaceId : undefined;
      return from !== to && hasDrafts();
    },
    enableBeforeUnload: hasDrafts,
    withResolver: true,
  });
  return (
    <Context.Provider value={sessions}>
      {children}
      <AlertDialog
        open={blocker.status === 'blocked'}
        onOpenChange={(open) => !open && blocker.reset?.()}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave without saving?</AlertDialogTitle>
            <AlertDialogDescription>Your file changes have not been saved.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Keep editing</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => blocker.proceed?.()}>
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Context.Provider>
  );
}
export const useOptionalFileSessions = () => useContext(Context);
export function useFileSessions() {
  const sessions = useOptionalFileSessions();
  if (!sessions) throw new Error('FileSessionsProvider is missing.');
  return sessions;
}
