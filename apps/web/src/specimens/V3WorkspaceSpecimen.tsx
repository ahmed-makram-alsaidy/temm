import { deriveProjectWorkspaceModel } from '../components/project-workspace-model';
import type {
  CompletionTaskEvidence,
  PlanTaskRecord,
  WorkspaceModelInput,
} from '../components/project-workspace-model';
import { ProjectWorkspace } from '../components/ProjectWorkspace';

export type V3SpecimenState = 'ready' | 'live' | 'attention' | 'verified' | 'empty';

interface V3WorkspaceSpecimenProps {
  state: V3SpecimenState;
  theme: 'light' | 'dark';
  rtl: boolean;
  grey: boolean;
}

const contracts = [
  { criterion_id: 'criterion-accessible', statement: 'The primary flow passes the recorded accessibility checks.', evaluator: { type: 'command' } },
  { criterion_id: 'criterion-responsive', statement: 'The workspace remains usable at the required viewports.', evaluator: { type: 'command' } },
];

const tasks: PlanTaskRecord[] = [
  { id: 'task-foundation', title: 'Establish the workspace foundation', description: 'Bind the approved visual primitives to the project truth model.', state: 'planned', dependency_ids: [], requirement_ids: ['requirement-workspace'], acceptance: contracts },
  { id: 'task-flow', title: 'Compose the outcome-to-evidence flow', description: 'Make current work, stops, attempts, and acceptance readable as one causal path.', state: 'planned', dependency_ids: ['task-foundation'], requirement_ids: ['requirement-workspace'], acceptance: contracts },
  { id: 'task-rtl', title: 'Validate Arabic and logical direction', description: 'Retain causal order while Arabic copy and controls read right-to-left.', state: 'planned', dependency_ids: ['task-flow'], requirement_ids: ['requirement-direction'], acceptance: contracts },
  { id: 'task-proof', title: 'Capture the static proof set', description: 'Record the required desktop, tablet, mobile, RTL, Chalk, and greyscale states.', state: 'planned', dependency_ids: ['task-rtl'], requirement_ids: ['requirement-evidence'], acceptance: contracts },
];

function measured(taskId: string, status: 'passed' | 'failed' = 'passed'): CompletionTaskEvidence {
  return {
    task_id: taskId,
    done: status === 'passed',
    criteria: contracts.map((contract) => ({
      id: contract.criterion_id,
      description: contract.statement,
      status,
      source: 'measured',
      evidence: { recorded: true },
    })),
  };
}

function specimenInput(state: V3SpecimenState, rtl: boolean): WorkspaceModelInput {
  const base: WorkspaceModelInput = {
    project: {
      id: 'project-workspace-v3',
      name: 'Flagship project workspace',
      purpose: rtl ? 'حوّل مسار المشروع إلى نتيجة موثقة يمكن تسليمها.' : 'Turn the project path into an evidence-backed deliverable.',
      slug: 'flagship-project-workspace',
    },
    stage: 'ready',
    blueprint: {
      id: 'blueprint-v3',
      revision: 3,
      status: 'approved',
      content: { goal: 'Compose the project path.', requirements: [] },
    },
    requirements: [
      { id: 'requirement-workspace', title: 'One continuous causal workspace', description: 'The outcome, work, evidence, and delivery read as one system.', status: 'approved', acceptance: contracts },
      { id: 'requirement-direction', title: 'English and Arabic parity', description: 'Direction is explicit and graph geometry remains causal.', status: 'approved', acceptance: [contracts[1]!] },
      { id: 'requirement-evidence', title: 'Truthful completion', description: 'Green and the Closed Cell appear only after measured acceptance.', status: 'approved', acceptance: [contracts[0]!] },
    ],
    plan: { tasks, orchestrations: [{ state: 'approved' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [] } },
    deliverables: [],
    readiness: { ready: true, workspace: { id: 'workspace-1', name: 'Approved workspace' }, blockers: [] },
    runDetails: {},
    isArabic: rtl,
  };

  if (state === 'empty') {
    return { ...base, stage: 'goal', blueprint: null, requirements: [], plan: { tasks: [], orchestrations: [] }, readiness: { ready: false, blockers: [] } };
  }

  if (state === 'live') {
    const liveTasks = tasks.map((task, index) => ({
      ...task,
      state: index === 0 ? 'completed' : index === 1 ? 'running' : 'planned',
      current_run_id: index === 0 ? 'run-foundation' : index === 1 ? 'run-flow' : null,
    }));
    return {
      ...base,
      stage: 'running',
      plan: { tasks: liveTasks, orchestrations: [{ state: 'running' }], needs: [] },
      completion: { ready: false, evidence: { tasks: [measured('task-foundation')] } },
      runDetails: {
        'task-foundation': { attempts: [{ id: 'attempt-foundation', attempt_number: 1, status: 'completed', executor_type: 'coding', receipt: { acceptance: contracts.map((contract) => ({ criterion_id: contract.criterion_id, description: contract.statement, status: 'passed', evidence: { recorded: true } })), duration_ms: 18420 } }] },
        'task-flow': { attempts: [
          { id: 'attempt-flow-1', attempt_number: 1, status: 'completed', executor_type: 'coding', receipt: { no_effect: true, duration_ms: 6210 } },
          { id: 'attempt-flow-2', attempt_number: 2, status: 'completed', executor_type: 'coding', receipt: { acceptance: [{ criterion_id: 'criterion-responsive', description: contracts[1]!.statement, status: 'failed', evidence: { viewport: 390 } }], duration_ms: 12980 } },
          { id: 'attempt-flow-3', attempt_number: 3, status: 'running', executor_type: 'coding' },
        ], output: [{ content: 'Current run output remains available as a collapsed technical receipt.' }] },
      },
    };
  }

  if (state === 'attention') {
    const stoppedTasks = tasks.map((task, index) => ({
      ...task,
      state: index === 0 ? 'completed' : index === 1 ? 'failed' : 'planned',
      current_run_id: index < 2 ? `run-${index + 1}` : null,
    }));
    return {
      ...base,
      stage: 'attention',
      plan: { tasks: stoppedTasks, orchestrations: [{ state: 'running' }], needs: [] },
      completion: { ready: false, evidence: { tasks: [measured('task-foundation'), measured('task-flow', 'failed')] } },
      runDetails: {
        'task-foundation': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { acceptance: [{ status: 'passed', evidence: { recorded: true } }] } }] },
        'task-flow': { attempts: [{ id: 'attempt-2', attempt_number: 1, status: 'completed', error_code: 'acceptance_failed', receipt: { acceptance: [{ criterion_id: 'criterion-responsive', description: contracts[1]!.statement, status: 'failed', evidence: { viewport: 390 } }], duration_ms: 11300 } }] },
      },
    };
  }

  if (state === 'verified') {
    const completedTasks = tasks.map((task, index) => ({ ...task, state: 'completed', current_run_id: `run-${index + 1}` }));
    return {
      ...base,
      stage: 'complete',
      plan: { tasks: completedTasks, orchestrations: [{ state: 'completed' }], needs: [] },
      completion: { ready: true, statement: 'All required acceptance contracts were measured and passed.', evidence: { tasks: tasks.map((task) => measured(task.id)) } },
      deliverables: [{ id: 'deliverable-v3', name: 'flagship-project-workspace', version: '1.0.0', readiness: 'ready', checksum: 'd8c77c4d462fe4b7d50d7c8dc40ae89f2b88e502c5743696585653f7e266bf18', download_path: '/api/projects/project-workspace-v3/deliverables/deliverable-v3/download' }],
    };
  }

  return base;
}

export function V3WorkspaceSpecimen({ state, theme, rtl, grey }: V3WorkspaceSpecimenProps) {
  const model = deriveProjectWorkspaceModel(specimenInput(state, rtl));
  return (
    <main
      className="temm-v3-specimen"
      data-specimen-state={state}
      data-specimen-theme={theme}
      style={grey ? { filter: 'grayscale(1)' } : undefined}
    >
      <ProjectWorkspace model={model} projects={[model.project]} onAction={() => undefined} />
    </main>
  );
}
