import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { expect } from '@playwright/test';
import { ports, project, root, state } from '../setup/settings.ts';

const execute = promisify(execFile);

async function ownedTemporal() {
  const admission = JSON.parse(await readFile(join(state, 'environment.json'), 'utf8'));
  if (admission.project !== project || admission.root !== root || typeof admission.run !== 'string') throw new Error('Temporal environment ownership mismatch');
  const { stdout } = await execute('docker', ['container', 'ls', '--all', '--quiet', '--filter', `label=com.docker.compose.project=${project}`, '--filter', 'label=com.docker.compose.service=temporal']);
  const id = stdout.trim();
  if (!id || /\s/.test(id)) throw new Error('Expected one owned Temporal container');
  const inspected = await execute('docker', ['container', 'inspect', id]);
  const labels = JSON.parse(inspected.stdout)[0].Config.Labels;
  if (labels['openlet.e2e.run'] !== admission.run || labels['openlet.e2e.worktree'] !== root) throw new Error('Temporal resource changed owner');
  return { admission, id };
}
async function temporal(args: string[]): Promise<string> {
  const { admission } = await ownedTemporal();
  const result = await execute('docker', ['compose', '--project-name', project, '--file', join(root, 'infra/compose/e2e.yaml'),
      'run', '--rm', '--no-deps', 'temporal-init', '--namespace', 'openlet', ...args], {
      cwd: root, timeout: 30_000, maxBuffer: 16 * 1024 * 1024,
      env: { ...process.env, OPENLET_E2E_ROOT: root, OPENLET_E2E_STATE: state, OPENLET_E2E_RUN: admission.run,
        OPENLET_E2E_GATEWAY_PORT: String(ports.gateway), OPENLET_E2E_CONTROL_PORT: String(ports.control), OPENLET_E2E_STORAGE_PORT: String(ports.storage) },
    });
  return result.stdout;
}

async function childExecution(parentId: string, type: string): Promise<string> {
  let id = '';
  await expect.poll(async () => {
    const history = JSON.parse(await temporal(['workflow', 'show', '--workflow-id', parentId, '--output', 'json']));
    const children = history.events.filter((event: any) => event.childWorkflowExecutionStartedEventAttributes?.workflowType?.name === type);
    id = children.at(-1)?.childWorkflowExecutionStartedEventAttributes?.workflowExecution?.workflowId ?? '';
    return id;
  }).not.toBe('');
  return id;
}

export async function workspaceDeletionExecution(workspaceId: string) {
  return childExecution(`workspace-changes/${workspaceId}`, 'DeleteWorkspace');
}
export async function filesystemDeletionIsRunning(workspaceId: string): Promise<boolean> {
  const deletion = await workspaceDeletionExecution(workspaceId);
  const id = await childExecution(deletion, 'DeleteFilesystem');
  const executions = JSON.parse(await temporal(['workflow', 'list', '--query', `WorkflowId = '${id}' AND ExecutionStatus = 'Running'`, '--limit', '1', '--output', 'json']));
  return executions.length === 1;
}
export async function terminateWorkspaceDeletion(workspaceId: string) {
  await temporal(['workflow', 'terminate', '--workflow-id', await workspaceDeletionExecution(workspaceId), '--reason', 'API recovery verification']);
}
export async function recordLatestHistory(name: string, type: string) {
  let id = '';
  await expect.poll(async () => {
    const executions = JSON.parse(await temporal(['workflow', 'list', '--query', `WorkflowType = '${type}' AND ExecutionStatus = 'Completed'`, '--limit', '1', '--output', 'json']));
    id = executions[0]?.execution?.workflowId ?? '';
    return id;
  }).not.toBe('');
  return recordWorkflowHistory(name, id);
}
export async function recordLifecycleHistories(subject: string, workspaceId: string) {
  const onboard = `onboard/${subject}`;
  await recordWorkflowHistory('OnboardUser', onboard);
  await recordWorkflowHistory('CreateWorkspace', await childExecution(onboard, 'CreateWorkspace'));
  const deletion = await workspaceDeletionExecution(workspaceId);
  await recordWorkflowHistory('DeleteWorkspace', deletion);
  const filesystemDeletion = await childExecution(deletion, 'DeleteFilesystem');
  await recordWorkflowHistory('DeleteFilesystem', filesystemDeletion);
  await recordWorkflowHistory('DeleteScope', await childExecution(filesystemDeletion, 'DeleteScope'));
  await recordWorkflowHistory('WorkspaceChanges', `workspace-changes/${workspaceId}`, false, true);
  await triggerStorageMaintenance();
  await recordLatestHistory('StorageMaintenance', 'StorageMaintenance');
  const workflowId = `replay/WorkspaceMaintenance/${randomUUID()}`;
  await temporal(['workflow', 'execute', '--workflow-id', workflowId, '--type', 'WorkspaceMaintenance', '--task-queue', 'openlet-workspace']);
  await recordWorkflowHistory('WorkspaceMaintenance', workflowId);
}

export async function setTemporalRunning(running: boolean) {
  const { id } = await ownedTemporal();
  await execute('docker', [running ? 'start' : 'stop', ...(running ? [] : ['--time', '10']), id], { timeout: 30_000 });
}
export async function temporalIsHealthy(): Promise<boolean> {
  try { await temporal(['operator', 'cluster', 'health']); return true; }
  catch { return false; }
}
export async function triggerStorageMaintenance() {
  await temporal(['schedule', 'trigger', '--schedule-id', 'openlet-storage-maintenance']);
}

export async function recordWorkflowHistory(name: string, workflowId: string, failed = false, running = false) {
  let output = '';
  const terminal = running ? 'EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_COMPLETED' : failed ? 'EVENT_TYPE_WORKFLOW_EXECUTION_FAILED' : 'EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED';
  await expect.poll(async () => {
    output = await temporal(['workflow', 'show', '--workflow-id', workflowId, '--output', 'json']);
    return JSON.parse(output).events.map((event: { eventType: string }) => event.eventType);
  }, { message: `${name} must finish before recording its replay fixture` }).toContain(terminal);
  const directory = join(state, 'histories');
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(join(directory, `${name}.json`), output, { mode: 0o600 });
  return output;
}
