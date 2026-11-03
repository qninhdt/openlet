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

export async function workspaceDeletionHasChild(workspaceId: string): Promise<boolean> {
  const history = JSON.parse(await temporal(['workflow', 'show', '--workflow-id', `delete-workspace/${workspaceId}`, '--output', 'json']));
  return history.events.some((event: { eventType: string }) => event.eventType === 'EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED');
}
export async function terminateWorkspaceDeletion(workspaceId: string) {
  await temporal(['workflow', 'terminate', '--workflow-id', `delete-workspace/${workspaceId}`, '--reason', 'API recovery verification']);
}

export async function recordLifecycleHistories(subject: string, workspaceId: string, userId: string) {
  const workflows: Record<string, string> = {
    OnboardUser: `onboard/${subject}`,
    CreateWorkspace: `create-workspace/${userId}/${userId}`,
    DeleteWorkspace: `delete-workspace/${workspaceId}`,
  };
  for (const name of ['OnboardUser', 'CreateWorkspace', 'DeleteWorkspace', 'DeleteFilesystem']) {
    const workflowId = workflows[name];
    const output = await recordWorkflowHistory(name, workflowId);
    const history = JSON.parse(output);
    if (name === 'DeleteWorkspace') {
      const child = history.events.find((event: { startChildWorkflowExecutionInitiatedEventAttributes?: { workflowType: { name: string } } }) => event.startChildWorkflowExecutionInitiatedEventAttributes?.workflowType.name === 'DeleteFilesystem');
      if (!child) throw new Error('Workspace did not start a filesystem child');
      workflows.DeleteFilesystem = child.startChildWorkflowExecutionInitiatedEventAttributes.workflowId;
    }
  }
  await triggerStorageMaintenance();
  let maintenanceId = '';
  await expect.poll(async () => {
    const completed = JSON.parse(await temporal(['workflow', 'list', '--query', "WorkflowType = 'StorageMaintenance' AND ExecutionStatus = 'Completed'", '--limit', '1', '--output', 'json']));
    maintenanceId = completed[0]?.execution?.workflowId ?? '';
    return maintenanceId;
  }).not.toBe('');
  await recordWorkflowHistory('StorageMaintenance', maintenanceId);
  for (const [name, queue] of [['WorkspaceMaintenance', 'openlet-workspace']]) {
    const workflowId = `replay/${name}/${randomUUID()}`;
    await temporal(['workflow', 'execute', '--workflow-id', workflowId, '--type', name, '--task-queue', queue]);
    await recordWorkflowHistory(name, workflowId);
  }
}

export async function setTemporalRunning(running: boolean) {
  const { id } = await ownedTemporal();
  await execute('docker', [running ? 'start' : 'stop', ...(running ? [] : ['--time', '10']), id], { timeout: 30_000 });
}
export async function temporalIsHealthy(): Promise<boolean> {
  try { await temporal(['operator', 'cluster', 'health']); return true; }
  catch { return false; }
}
export async function recordCopyHistory(name: 'CopyNode' | 'CopyNodeRecovery', filesystemId: string, copyId: string, continued = false) {
  const directory = join(state, 'histories');
  const workflowId = `copy/${filesystemId}/${copyId}`;
  const output = await recordWorkflowHistory(name, workflowId);
  const history = JSON.parse(output);
  const started = history.events[0].workflowExecutionStartedEventAttributes;
  if (continued && !started.continuedExecutionRunId) throw new Error('Copy did not Continue-As-New');
  if (continued) {
    const previous = await temporal(['workflow', 'show', '--workflow-id', workflowId, '--run-id', started.continuedExecutionRunId, '--output', 'json']);
    await writeFile(join(directory, 'CopyNodeContinued.json'), previous, { mode: 0o600 });
  }
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
