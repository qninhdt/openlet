import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

export const root = fileURLToPath(new URL('../../', import.meta.url));
export const state = join(root, '.local/api-e2e');
export const project = 'openlet-api-e2e';
export const ports = { gateway: 18200, control: 18201, storage: 18202 };
export const gateway = `http://127.0.0.1:${ports.gateway}`;
export const control = `http://127.0.0.1:${ports.control}`;
