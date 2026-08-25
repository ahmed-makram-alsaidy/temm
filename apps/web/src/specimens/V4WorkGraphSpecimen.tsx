import { deriveProjectWorkspaceModel } from '../components/project-workspace-model';
import type {
  CompletionTaskEvidence,
  PlanTaskRecord,
  RunDetailRecord,
  WorkspaceModelInput,
} from '../components/project-workspace-model';
import { ProjectWorkspace } from '../components/ProjectWorkspace';

interface V4WorkGraphSpecimenProps {
  taskCount: 1 | 6 | 24 | 40 | 120;
  theme: 'light' | 'dark';
  rtl: boolean;
  grey: boolean;
  sheetTaskId?: string | null;
}

const acceptance = [{
  criterion_id: 'criterion-output',
  statement: 'The required workspace effect is measured and accepted.',
  evaluator: { type: 'changed_files_subset' },
}];

function acceptedEvidence(taskId: string): CompletionTaskEvidence {
  return {
    task_id: taskId,
    done: true,
    criteria: [{
      id: 'criterion-output',
      description: acceptance[0]!.statement,
      status: 'passed',
      source: 'measured',
      evidence: { path: `src/${taskId}.ts` },
    }],
  };
}

function specimenInput(taskCount: number, rtl: boolean): WorkspaceModelInput {
  const completedCount = taskCount === 1 ? 0 : Math.max(1, Math.floor(taskCount * .15));
  const activeCount = Math.min(2, taskCount - completedCount);
  const tasks: PlanTaskRecord[] = Array.from({ length: taskCount }, (_, index) => {
    const id = `task-${String(index + 1).padStart(3, '0')}`;
    const dependencies = index === 0 ? [] : [`task-${String(index).padStart(3, '0')}`];
    const active = index >= completedCount && index < completedCount + activeCount;
    return {
      id,
      title: rtl ? `مهمة التنفيذ ${index + 1}` : `Execution task ${index + 1}`,
      description: rtl ? 'عمل مرتب حسب الاعتماد مع أثر وقبول قابلين للقياس.' : 'Dependency-ordered work with independently measured effect and acceptance.',
      state: index < completedCount ? 'completed' : active ? 'running' : 'planned',
      dependency_ids: dependencies,
      requirement_ids: [`requirement-${(index % 4) + 1}`],
      acceptance,
      current_run_id: index < completedCount || active ? `run-${id}` : null,
    };
  });
  const runDetails = Object.fromEntries(tasks.filter((task) => task.current_run_id).map((task, index) => {
    const taskIndex = tasks.findIndex((item) => item.id === task.id);
    const active = task.state === 'running';
    const attempts: NonNullable<RunDetailRecord['attempts']> = active && index === completedCount
      ? [
        { id: `${task.id}-attempt-1`, attempt_number: 1, status: 'failed', executor_type: 'coding', model_id: 'model-route-a', receipt: { no_effect: true, duration_ms: 4200 } },
        { id: `${task.id}-attempt-2`, attempt_number: 2, status: 'failed', executor_type: 'coding', model_id: 'model-route-b', receipt: { workspace_diff: [{ path: `src/${task.id}.ts` }], acceptance: [{ criterion_id: 'criterion-output', description: acceptance[0]!.statement, status: 'failed', evidence: { reason: 'contract mismatch' } }], duration_ms: 6800 } },
        { id: `${task.id}-attempt-3`, attempt_number: 3, status: 'running', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-c', started_at: '2026-08-24T10:00:20Z' },
      ]
      : active
        ? [{ id: `${task.id}-attempt-1`, attempt_number: 1, status: 'running', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-a', started_at: '2026-08-24T10:00:30Z' }]
        : [{
          id: `${task.id}-attempt-1`, attempt_number: 1, status: 'completed', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-a',
          started_at: '2026-08-24T09:59:40Z', completed_at: '2026-08-24T09:59:52Z',
          receipt: { workspace_diff: [{ path: `src/${task.id}.ts` }], acceptance: [{ criterion_id: 'criterion-output', description: acceptance[0]!.statement, status: 'passed', evidence: { path: `src/${task.id}.ts` } }], duration_ms: 12000 },
        }];
    return [task.id, {
      run: {
        id: task.current_run_id!, status: active ? 'running' : 'completed', routing_mode: 'balanced',
        selected_agent_id: 'coder', selected_model_id: 'model-route-a',
        current_attempt_id: attempts.at(-1)?.id, duration_ms: active ? 0 : 12000 + taskIndex,
        latency_provenance: 'measured', started_at: '2026-08-24T09:59:40Z', completed_at: active ? null : '2026-08-24T09:59:52Z',
      },
      attempts,
      artifacts: active ? [] : [{ id: `artifact-${task.id}`, attempt_id: attempts[0]?.id, path: `src/${task.id}.ts`, sha256: 'measured' }],
    } satisfies RunDetailRecord];
  }));
  return {
    project: {
      id: `project-v4-${taskCount}`,
      name: rtl ? 'شبكة العمل الحية' : 'Live task lattice',
      purpose: rtl ? 'اربط المهمة بالتشغيل والمحاولة والأثر والقبول والدليل.' : 'Map task to run, attempt, effect, acceptance, and evidence.',
    },
    stage: 'running',
    blueprint: { id: 'blueprint-v4', revision: 4, status: 'approved' },
    requirements: Array.from({ length: 4 }, (_, index) => ({
      id: `requirement-${index + 1}`,
      title: rtl ? `مجموعة العمل ${index + 1}` : `Work group ${index + 1}`,
      status: 'approved',
      acceptance,
    })),
    plan: { tasks, orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: tasks.slice(0, completedCount).map((task) => acceptedEvidence(task.id)) } },
    deliverables: [],
    readiness: { ready: true, workspace: { id: 'workspace-v4', name: 'Measured workspace' }, blockers: [] },
    runDetails,
    isArabic: rtl,
  };
}

export function V4WorkGraphSpecimen({ taskCount, theme, rtl, grey, sheetTaskId = null }: V4WorkGraphSpecimenProps) {
  const model = deriveProjectWorkspaceModel(specimenInput(taskCount, rtl));
  return (
    <main
      className="temm-v3-specimen"
      data-specimen-state="live"
      data-specimen-theme={theme}
      data-v4-task-count={taskCount}
      data-v4-scale={model.work.scale}
      data-v4-active-count={model.work.activeCount}
      style={grey ? { filter: 'grayscale(1)' } : undefined}
    >
      <ProjectWorkspace model={model} projects={[model.project]} onAction={() => undefined} initialSheetTaskId={sheetTaskId} />
    </main>
  );
}
