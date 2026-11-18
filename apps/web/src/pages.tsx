import { Outlet } from '@tanstack/react-router';
import { AuthProvider, BackendProvider } from '@/lib/backend';
import { WorkspaceDirectory } from '@/lib/workspace-directory';

export function RootLayout() {
  return (
    <AuthProvider>
      <a
        href="#main-content"
        className="sr-only rounded-md bg-background p-3 focus:not-sr-only focus:absolute focus:z-50"
      >
        Skip to content
      </a>
      <Outlet />
    </AuthProvider>
  );
}
export function WorkspacePage() {
  return (
    <BackendProvider>
      <WorkspaceDirectory>
        <Outlet />
      </WorkspaceDirectory>
    </BackendProvider>
  );
}
