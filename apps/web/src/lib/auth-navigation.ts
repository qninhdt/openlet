export const publishableKey = import.meta.env?.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

export function safeReturnTo(value: unknown) {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    /[\\\r\n]/.test(value)
  )
    return '/app';
  const url = new URL(value, 'https://openlet.invalid');
  if (url.origin !== 'https://openlet.invalid') return '/app';
  return /^\/(app(?:\/|$)|workspaces(?:\/|$)|join(?:\/|$))/.test(url.pathname)
    ? url.pathname + url.search + url.hash
    : '/app';
}
