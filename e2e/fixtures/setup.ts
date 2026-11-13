import { request, expect } from '@playwright/test';
import { generateKeyPair, exportJWK } from 'jose';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { parse } from 'yaml';

export default async function setup() {
  const config = parse(readFileSync(new URL('../openlet.test.yaml', import.meta.url), 'utf8'));
  const directory = mkdtempSync(join(tmpdir(), 'openlet-e2e-'));
  const keys = await generateKeyPair('RS256', { extractable: true });
  const kid = randomUUID();
  process.env.OPENLET_TEST_KEY = join(directory, 'signing-key.json');
  writeFileSync(
    process.env.OPENLET_TEST_KEY,
    JSON.stringify({ ...(await exportJWK(keys.privateKey)), kid }),
    { mode: 0o600 },
  );
  const admin = await request.newContext({ baseURL: new URL(config.auth.clerk.api_url).origin });
  try {
    const response = await admin.post('/__admin/mappings', {
      data: {
        request: { method: 'GET', urlPath: '/.well-known/jwks.json' },
        response: {
          status: 200,
          jsonBody: {
            keys: [{ ...(await exportJWK(keys.publicKey)), kid, alg: 'RS256', use: 'sig' }],
          },
          headers: { 'Content-Type': 'application/json' },
        },
      },
    });
    expect(response.ok()).toBeTruthy();
  } finally {
    await admin.dispose();
  }
  return () => {
    rmSync(directory, { recursive: true });
  };
}
