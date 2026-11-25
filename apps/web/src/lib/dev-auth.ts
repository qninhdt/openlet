export const devAuthEnabled =
  Boolean(import.meta.env?.DEV) && import.meta.env?.VITE_DEV_AUTH === '1';

export type DevAccount = {
  handle: string;
  user_id: string;
  clerk_user_id: string;
  email: string;
  name: string;
  token: string;
};

const STORAGE_KEY = 'openlet-dev-account';

export function readDevAccount(): DevAccount | null {
  if (!devAuthEnabled) return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DevAccount) : null;
  } catch {
    return null;
  }
}

export function writeDevAccount(account: DevAccount): void {
  if (!devAuthEnabled) return;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(account));
}

export function clearDevAccount(): void {
  if (!devAuthEnabled) return;
  sessionStorage.removeItem(STORAGE_KEY);
}

export async function fetchDevAccounts(): Promise<DevAccount[]> {
  if (!devAuthEnabled) return [];
  const res = await fetch('/__dev/accounts');
  if (!res.ok) return [];
  const body = (await res.json()) as { accounts?: DevAccount[] };
  return body.accounts ?? [];
}
