/**
 * API Service for AI Fleet OS Command Center.
 */

const API_BASE = (import.meta.env.VITE_API_URL as string) || "";

export interface FleetOverview {
  fleet_counts: {
    models_total: number;
    models_online: number;
    models_unavailable: number;
    agents_total: number;
    agents_ready: number;
    skills_total: number;
    workflows_total: number;
    providers_count: number;
    models_registered?: number;
    providers_registered?: number;
    workspaces_count?: number;
    execution_ready?: boolean;
  };
  operational_metrics: {
    source: 'canonical_analytics';
    endpoint: string;
    financials: null;
    tokens: null;
    tasks: null;
  };
}

export interface AnalyticsSummary {
  range: { start: string; end: string; end_exclusive: boolean };
  runs: { total: number; statuses: Record<string, number>; fallback_runs: number };
  usage_by_provenance: Record<'provider_reported' | 'measured' | 'estimated', { requests: number; input_tokens: number; output_tokens: number; cached_tokens: number; reasoning_tokens: number }>;
  unknown_usage_observations: number;
  financials: { provider_reported_actual_cost: string; estimated_actual_cost: string; direct_saving: string; estimated_avoided_cost: string; equivalent_api_value: string; unknown_actual_cost_runs: number };
}

export interface Model {
  id: string;
  name: string;
  provider: string;
  category: string;
  modalities: string[];
  input_cost_per_m: number;
  output_cost_per_m: number;
  cache_cost_per_m: number;
  context_window: number;
  is_local: boolean;
  is_free: boolean;
  is_active: boolean;
  is_reference_baseline: boolean;
  quality_score: number | null;
  coding_score: number | null;
  reasoning_score: number | null;
  arabic_score: number | null;
  vision_score: number | null;
  speed_score: number | null;
  tokens_per_sec: number | null;
  reliability_score: number | null;
  registry_state: string;
  lifecycle_status: string;
  availability_state: string;
  availability_evidence: Record<string, any>;
  availability_checked_at?: string | null;
  source_type: string;
  source_uri: string;
  metadata_provenance: string;
  pricing_provenance: string;
  capability_provenance: string;
  best_for: string[];
  not_ideal_for: string[];
  description: string;
}

export interface Agent {
  id: string;
  name: string;
  cli_command: string;
  version_command: string;
  prompt_arg_format: string;
  workspace_arg_format: string;
  input_method: string;
  output_method: string;
  supports_pty: boolean;
  supports_interactive: boolean;
  capabilities: string[];
  tool_kind: 'agent' | 'runtime';
  adapter_id: string;
  discovery_state: 'verified' | 'detected' | 'unverified' | 'unavailable' | 'broken';
  discovery_source: 'manifest' | 'manual';
  discovery_evidence: Record<string, any>;
  version_probe_args: string[];
  health_probe_args: string[];
  invocation_args: string[];
  environment_refs: string[];
  secret_refs: string[];
  working_directory: 'workspace' | 'inherit';
  probe_timeout_seconds: number;
  last_checked_at?: string | null;
  user_enabled: boolean;
  lifecycle_status: 'active' | 'retired';
  revision: number;
  auth_state: 'not_required' | 'unknown' | 'configured' | 'verified' | 'failed';
  auth_method: string;
  auth_evidence: Record<string, any>;
  auth_checked_at?: string | null;
  auth_setup_action: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
  permission_profile: string;
  is_installed: boolean;
  detected_path: string;
  version: string;
  status: string;
  execution_ready?: boolean;
  auth_status?: string;
  auth_message?: string;
  setup_command?: string | null;
  description: string;
}

export interface TaskRun {
  id: string;
  prompt: string;
  task_type: string;
  selected_model_id?: string | null;
  selected_agent_id?: string | null;
  workspace_id?: string | null;
  project_id?: string | null;
  workflow_id?: string | null;
  current_attempt_id?: string | null;
  status_reason?: string | null;
  routing_mode: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  actual_cost: number | null;
  reference_cost: number | null;
  saved_amount: number | null;
  saving_percentage: number | null;
  duration_ms: number;
  quality_eval_score: number | null;
  token_provenance: 'measured' | 'provider_reported' | 'estimated' | 'unknown';
  cost_provenance: 'measured' | 'provider_reported' | 'estimated' | 'unknown';
  quality_provenance: 'measured' | 'provider_reported' | 'estimated' | 'unknown';
  latency_provenance: 'measured' | 'provider_reported' | 'estimated' | 'unknown';
  measurement_metadata: Record<string, any>;
  financials: {
    actual_cost?: { amount: string | null; currency: string | null; provenance: string; method: string | null };
    reference_cost?: { amount: string | null; currency: string | null; provenance: string; method: string | null };
    value?: { category: string; amount: string | null; currency: string | null; provenance: string; method: string | null };
  };
  route_explanation: string;
  fallback_chain: string[];
  log_output: string;
  result_output: string;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  title: string;
  model_id: string;
  routing_mode: string;
  total_tokens: number;
  total_saved: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  model_used?: string;
  provider_used?: string;
  tokens: number;
  cost: number;
  saved: number;
  latency_ms: number;
  created_at: string;
}

export interface TerminalExecResult {
  id?: string | null;
  workspace_id?: string | null;
  command: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
  success: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  path: string;
  permission_profile: 'safe' | 'developer' | 'full';
  allowed_shells: Array<'powershell' | 'cmd'>;
  is_default: boolean;
  created_at: string;
  last_used_at?: string | null;
}

export interface CommandRun extends TerminalExecResult {
  id: string;
  workspace_id: string;
  shell: string;
  status: string;
  created_at: string;
}

export interface ProviderInstance {
  id: string;
  name: string;
  adapter_id: string;
  protocol_version: string;
  capabilities: string[];
  configuration: Record<string, string | number | boolean | null>;
  secret_refs: string[];
  lifecycle_status: string;
  user_enabled: boolean;
  health_state: string;
  health_evidence: Record<string, any>;
  health_checked_at?: string | null;
  health_expires_at?: string | null;
  revision: number;
}

export interface PluginRecord {
  id: string;
  name: string;
  path: string;
  version: string;
  protocol_version: string;
  plugin_type: string;
  status: string;
  permissions: string[];
  granted_permissions: string[];
  permission_profile: string;
  package_hash: string;
  entrypoint: string;
  load_state: string;
  source_type: string;
  source_id?: string | null;
  source_package_url?: string | null;
  previous_hash?: string | null;
  installed_at?: string | null;
  manifest: Record<string, any>;
  created_at: string;
}

export interface PluginCatalogSource {
  id: string;
  index_url: string;
  enabled: boolean;
  last_state: string;
  last_error: string;
  entry_count: number;
  verified_at?: string | null;
  expires_at?: string | null;
}

export interface MarketplaceBenchmarkPack {
  source_id: string;
  identity: { id: string; version: string };
  pack: { id: string; version: string; schema_version: string; category: string; name: string };
  author: string;
  source_code_url: string;
  package: { url: string; sha256: string; size: number; media_type: string };
  reputation: string;
  executable: false;
  catalog_expires_at: string;
}

export interface MarketplaceWorkflowTemplate {
  source_id: string;
  identity: { id: string; version: string };
  template: { id: string; version: string; schema_version: string; name: string; prerequisites: string[]; gate_ids: string[] };
  author: string;
  package: { url: string; sha256: string; size: number; media_type: string };
  reputation: string;
  executable: false;
  catalog_expires_at: string;
}

export interface MarketplacePlugin {
  source_id: string;
  manifest: { id: string; name: string; version: string; type: string; protocol: string; permissions: string[]; capabilities: string[] };
  author: string;
  source_code_url: string;
  package: { url: string; sha256: string; folder_sha256: string; size: number };
  compatible: boolean;
  platform_supported: boolean;
  permissions: string[];
  reputation: string;
  requires_permission_review: boolean;
  catalog_expires_at: string;
}

export interface PluginInspection {
  valid: boolean;
  folder_path: string;
  plugin_id: string;
  name: string;
  version: string;
  protocol_version: string;
  plugin_type: string;
  permissions: string[];
  checklist: Record<string, boolean>;
  executes_code: boolean;
  compatible: boolean;
  package_hash: string;
  entrypoint: string;
}

export interface RouteRecommendation {
  selected_model: Model;
  routing_mode: string;
  task_analysis: {
    category: string;
    complexity: number;
    is_arabic: boolean;
    is_coding: boolean;
    is_reasoning: boolean;
    word_count: number;
    estimated_input_tokens: number;
  };
  score: number;
  estimated_cost: number | null;
  reference_baseline_cost: number | null;
  estimated_saved: number | null;
  saving_percentage: number | null;
  reasons: string[];
  explanation: string;
  fallback_chain: string[];
  alternatives: Array<{
    model: Model;
    score: number;
    estimated_cost: number | null;
  }>;
}

export interface ExecutionBlocker {
  code: string;
  title: string;
  detail: string;
  provider?: string;
  setup_command?: string;
  action_target: 'settings' | 'fleet' | 'workspaces';
}

export interface TaskPreflight {
  can_execute: boolean;
  execution_method: 'cli' | 'provider_api' | null;
  recommendation: RouteRecommendation;
  selected_model: Model | null;
  selected_agent: Agent | null;
  selected_workspace: Workspace | null;
  workspaces: Workspace[];
  recommended_model: Model;
  recommended_model_state: { ready: boolean; code: string; detail: string };
  blockers: ExecutionBlocker[];
  installed_tools: Agent[];
  connections: Record<string, { provider: string; is_configured: boolean; source: string; masked_key: string }>;
  ollama_status: { running: boolean; host: string; models: Array<{ name: string }> };
  pty: { supported: boolean; backend: string | null; reason: string | null; features: string[] };
  interactive: boolean;
}

export const api = {
  async getOverview(): Promise<FleetOverview> {
    const res = await fetch(`${API_BASE}/api/fleet/overview`);
    return res.json();
  },

  async getAnalytics(start: Date, end: Date): Promise<AnalyticsSummary> {
    const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
    const res = await fetch(`${API_BASE}/api/analytics/summary?${params}`);
    if (!res.ok) throw new Error('Could not load analytics.');
    return res.json();
  },

  async globalSearch(query: string, projectId?: string): Promise<any> {
    const params = new URLSearchParams({ q: query }); if (projectId) params.set('project_id', projectId);
    const res = await fetch(`${API_BASE}/api/search?${params}`); return res.json();
  },

  async listProjects(includeArchived = false): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects?include_archived=${includeArchived}`);
    return res.json();
  },

  async createProject(values: { name: string; purpose: string; slug?: string; project_type?: string }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Project creation failed.'); return data;
  },

  async setProjectArchived(projectId: string, archived: boolean): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/${archived ? 'archive' : 'restore'}`, { method: 'POST' });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Project lifecycle update failed.'); return data;
  },

  async getProjectValue(projectId: string): Promise<any> {
    const now = new Date(); const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    const params = new URLSearchParams({ start: start.toISOString(), end: now.toISOString() });
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/value?${params}`); return res.json();
  },

  async getProjectRequirements(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/requirements/view`); return res.json();
  },

  async updateProjectRequirement(requirementId: string, expectedRevision: number, values: Record<string, unknown>): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/requirements/${requirementId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: expectedRevision, ...values }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Requirement update failed.'); return data;
  },

  async approveProjectRequirement(requirementId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/requirements/${requirementId}/transition`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: 'approved', actor: 'local_owner' }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Requirement approval failed.'); return data;
  },

  async getProjectPlan(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan`); return res.json();
  },

  async getProjectCompletion(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/completion`); return res.json();
  },

  async getProjectExecutionReadiness(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/execution-readiness`); const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Could not check project readiness.'); return data;
  },

  async listProjectWorkspaces(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/workspaces`); const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Could not load project folders.'); return data;
  },

  async bindProjectWorkspace(projectId: string, workspaceId: string, role = 'primary'): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/workspaces`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: workspaceId, role }) }); const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Could not connect the project folder.'); return data;
  },

  async createBlueprintFromGoal(projectId: string, goal: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/blueprints/from-goal`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Blueprint generation failed.'); return data;
  },

  async compileProjectPlan(projectId: string, proposalId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan/compile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal_id: proposalId }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Project plan compilation failed.'); return data;
  },

  async createOrchestration(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/orchestrations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: projectId }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Project execution setup failed.'); return data;
  },

  async dispatchOrchestration(id: string, workspaceId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/orchestrations/${id}/dispatch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: workspaceId, max_tasks: 1 }) });
    const data = await res.json(); if (!res.ok) { const error = new Error(data?.detail?.message || 'Project execution could not start.') as Error & { details?: any }; error.details = data?.detail; throw error; } return data;
  },

  async packageProjectDeliverable(projectId: string, values: { workspace_id: string; name: string; version: string; relative_paths: string[] }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/deliverables/package`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Deliverable packaging failed.'); return data;
  },

  async commandOrchestration(id: string, action: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/orchestrations/${id}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ payload: {} }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Orchestration command failed.'); return data;
  },

  async listProjectDeliverables(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/deliverables`); return res.json();
  },

  async getProjectResearch(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/research`); return res.json();
  },

  async getProjectQuality(projectId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/quality`); return res.json();
  },

  async listAssets(projectId?: string): Promise<any[]> {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const res = await fetch(`${API_BASE}/api/assets${params}`); return res.json();
  },

  async getAsset(assetId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/assets/${assetId}`); return res.json();
  },

  async listAssetCollections(projectId?: string): Promise<any[]> {
    const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const res = await fetch(`${API_BASE}/api/asset-library${params}`); return res.json();
  },

  async listProjectContextPacks(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/context-packs`); return res.json();
  },

  async listProjectDecisions(projectId: string, status = ''): Promise<any[]> {
    const params = status ? `?status=${encodeURIComponent(status)}` : '';
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/decisions${params}`); return res.json();
  },

  async createProjectDecision(projectId: string, value: any): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/decisions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Decision creation failed.'); return data;
  },

  async decideProjectDecision(decisionId: string, action: 'approve' | 'reject'): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/decisions/${decisionId}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor: 'local_owner' }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Decision update failed.'); return data;
  },

  async listProjectBrain(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/brain`); return res.json();
  },

  async listProjectBrainRevisions(factId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/brain/facts/${factId}/revisions`); return res.json();
  },

  async mergeProjectBrainFact(projectId: string, value: any): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/brain/facts`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Brain fact update failed.'); return data;
  },

  async listBlueprints(projectId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/blueprints`); return res.json();
  },

  async approveBlueprint(proposalId: string, expectedRevision: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/projects/blueprints/${proposalId}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: expectedRevision, actor: 'local_owner' }) });
    const data = await res.json(); if (!res.ok) throw new Error(data?.detail?.message || 'Blueprint approval failed.'); return data;
  },

  async listModels(category?: string): Promise<Model[]> {
    const url = category ? `${API_BASE}/api/models?category=${category}` : `${API_BASE}/api/models`;
    const res = await fetch(url);
    return res.json();
  },

  async setModelFavorite(modelId: string, useCase: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/models/${encodeURIComponent(modelId)}/favorites`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ use_case: useCase }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Favorite update failed.');
    return data;
  },

  async toggleModelActive(modelId: string): Promise<{ id: string; is_active: boolean }> {
    const res = await fetch(`${API_BASE}/api/models/${modelId}/toggle-active`, { method: "PATCH" });
    return res.json();
  },

  async setReferenceBaseline(modelId: string): Promise<{ status: string; baseline_model_id: string }> {
    const res = await fetch(`${API_BASE}/api/models/${modelId}/set-baseline`, { method: "PATCH" });
    return res.json();
  },

  async listAgents(): Promise<Agent[]> {
    const res = await fetch(`${API_BASE}/api/agents`);
    return res.json();
  },

  async inspectAgent(payload: { executable: string; version_probe_args: string[]; timeout_seconds: number }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/agents/inspect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Inspection failed.');
    return data;
  },

  async addAgent(payload: Record<string, unknown>): Promise<Agent> {
    const res = await fetch(`${API_BASE}/api/agents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Could not add agent.');
    return data;
  },

  async updateAgent(agentId: string, payload: Record<string, unknown>): Promise<Agent> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Agent update failed.');
    return data;
  },

  async deleteAgent(agentId: string): Promise<{ agent_id: string; deleted: boolean; retired: boolean; history_preserved: boolean }> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Agent removal failed.');
    return data;
  },

  async checkAgentAuth(agentId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}/auth/check`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Authentication check failed.');
    return data;
  },

  async listAgentSecrets(agentId: string): Promise<Array<{ reference: string; configured: boolean }>> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}/secrets`);
    return res.json();
  },

  async setAgentSecret(agentId: string, reference: string, value: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}/secrets`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference, value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not save credential.');
    return data;
  },

  async deleteAgentSecret(agentId: string, reference: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}/secrets/${encodeURIComponent(reference)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not remove credential.');
    return data;
  },

  async rescanAgent(agentId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/agents/${agentId}/rescan`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Rescan failed.');
    return data;
  },

  async triggerScan(): Promise<any> {
    const res = await fetch(`${API_BASE}/api/scanner/detect`, { method: "POST" });
    return res.json();
  },

  async getRecommendation(prompt: string, mode: string, customWeights?: any): Promise<RouteRecommendation> {
    const res = await fetch(`${API_BASE}/api/router/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, mode, custom_weights: customWeights }),
    });
    return res.json();
  },

  async preflightTask(payload: { prompt: string; model_id?: string; agent_id?: string; workspace_id?: string; routing_mode?: string; interactive?: boolean }): Promise<TaskPreflight> {
    const res = await fetch(`${API_BASE}/api/tasks/preflight`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Preflight failed (${res.status})`);
    return res.json();
  },

  async runTask(payload: { task_id?: string; prompt: string; model_id?: string; agent_id?: string; workspace_id?: string; routing_mode?: string; interactive?: boolean; terminal_columns?: number; terminal_rows?: number }): Promise<TaskRun> {
    const res = await fetch(`${API_BASE}/api/tasks/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      const message = data?.detail?.message || data?.detail || `Execution failed (${res.status})`;
      throw new Error(typeof message === 'string' ? message : 'Execution is not ready.');
    }
    return data;
  },

  openTaskStream(taskId: string, onEvent: (event: any) => void): WebSocket {
    const wsBase = API_BASE.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/ws/terminal/${taskId}`);
    socket.onmessage = (message) => {
      try { onEvent(JSON.parse(message.data)); } catch { return; }
    };
    return socket;
  },

  async cancelTask(taskId: string): Promise<{ task_id: string; status: string; state: string }> {
    const res = await fetch(`${API_BASE}/api/tasks/${taskId}/cancel`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || `Cancellation failed (${res.status})`);
    return data;
  },

  async listRuns(): Promise<TaskRun[]> {
    const res = await fetch(`${API_BASE}/api/runs`);
    return res.json();
  },

  async getRun(runId: string): Promise<TaskRun> {
    const res = await fetch(`${API_BASE}/api/runs/${runId}`); if (!res.ok) throw new Error('Run not found.'); return res.json();
  },

  async compareRuns(runIds: string[]): Promise<any> {
    const params = new URLSearchParams();
    runIds.forEach((id) => params.append('run_id', id));
    const res = await fetch(`${API_BASE}/api/runs/compare?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Run comparison failed.');
    return data;
  },

  async getRunDetails(runId: string): Promise<any> {
    const paths = ['attempts', 'events', 'output', 'artifacts', 'usage', 'latency'];
    const results = await Promise.all(paths.map(async (path) => {
      const res = await fetch(`${API_BASE}/api/runs/${runId}/${path}`);
      if (!res.ok) throw new Error(`Could not load run ${path}.`);
      return res.json();
    }));
    return Object.fromEntries(paths.map((path, index) => [path, results[index]]));
  },

  async cancelRun(runId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/runs/${runId}/cancel`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Run cancellation failed.');
    return data;
  },

  async getTaskHistory(): Promise<TaskRun[]> {
    const res = await fetch(`${API_BASE}/api/tasks/history`);
    return res.json();
  },

  // Chat Studio API
  async listChatSessions(): Promise<ChatSession[]> {
    const res = await fetch(`${API_BASE}/api/chat/sessions`);
    return res.json();
  },

  async createChatSession(title?: string, modelId?: string, routingMode?: string): Promise<ChatSession> {
    const res = await fetch(`${API_BASE}/api/chat/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, model_id: modelId, routing_mode: routingMode }),
    });
    return res.json();
  },

  async getSessionMessages(sessionId: string): Promise<ChatMessage[]> {
    const res = await fetch(`${API_BASE}/api/chat/sessions/${sessionId}/messages`);
    return res.json();
  },

  async sendChatMessage(payload: { session_id: string; message: string; model_id?: string; routing_mode?: string }): Promise<{
    user_message: ChatMessage;
    assistant_message: ChatMessage;
    model_used: string;
    saved_vs_baseline: string;
    duration_ms: number;
  }> {
    const res = await fetch(`${API_BASE}/api/chat/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  // Terminal Runner API
  async requestApproval(payload: { action_type: string; scope_type: string; scope_id: string; summary: string; details?: Record<string, unknown>; ttl_seconds?: number }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/approvals`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Approval request failed.');
    return data;
  },

  async decideApproval(approvalId: string, approve: boolean, reason: string = ''): Promise<any> {
    const res = await fetch(`${API_BASE}/api/approvals/${approvalId}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approve, reason }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Approval decision failed.');
    return data;
  },

  async runTerminal(command: string, shell: string = "powershell", workspaceId?: string, approvalId?: string): Promise<TerminalExecResult> {
    const res = await fetch(`${API_BASE}/api/terminal/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, shell, workspace_id: workspaceId, approval_id: approvalId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `Command failed (${res.status})`);
    return data;
  },

  async listCommandHistory(workspaceId?: string): Promise<CommandRun[]> {
    const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
    const res = await fetch(`${API_BASE}/api/terminal/history${query}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Settings update failed.');
    return data;
  },

  async listWorkspaces(): Promise<Workspace[]> {
    const res = await fetch(`${API_BASE}/api/workspaces`);
    return res.json();
  },

  async createWorkspace(payload: { name: string; path: string; permission_profile: string; allowed_shells: string[]; is_default?: boolean }): Promise<Workspace> {
    const res = await fetch(`${API_BASE}/api/workspaces`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not add workspace.');
    return data;
  },

  async updateWorkspace(workspaceId: string, payload: Partial<Workspace>): Promise<Workspace> {
    const res = await fetch(`${API_BASE}/api/workspaces/${workspaceId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    return res.json();
  },

  async removeWorkspace(workspaceId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/workspaces/${workspaceId}`, { method: 'DELETE' });
    return res.json();
  },

  async listProviderInstances(): Promise<ProviderInstance[]> {
    const res = await fetch(`${API_BASE}/api/providers`);
    return res.json();
  },

  async updateProviderInstance(providerId: string, payload: Record<string, unknown>): Promise<ProviderInstance> {
    const res = await fetch(`${API_BASE}/api/providers/${providerId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Provider update failed.');
    return data;
  },

  async archiveProviderInstance(providerId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/providers/${providerId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Provider archive failed.');
    return data;
  },

  async listProviderSecrets(providerId: string): Promise<Array<{ reference: string; configured: boolean }>> {
    const res = await fetch(`${API_BASE}/api/providers/${providerId}/secrets`);
    return res.json();
  },

  async setProviderSecret(providerId: string, reference: string, value: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/providers/${providerId}/secrets`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference, value }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Provider credential update failed.');
    return data;
  },

  async reloadPlugin(pluginId: string): Promise<PluginRecord> {
    const res = await fetch(`${API_BASE}/api/plugins/${pluginId}/reload`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Plugin reload failed.');
    return data;
  },

  async runPluginConformance(pluginId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/plugins/${pluginId}/conformance`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Plugin conformance failed.');
    return data;
  },

  async listPlugins(): Promise<PluginRecord[]> {
    const res = await fetch(`${API_BASE}/api/plugins`);
    return res.json();
  },

  async listMarketplaceSources(): Promise<PluginCatalogSource[]> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/sources`);
    return res.json();
  },

  async addMarketplaceSource(payload: { source_id: string; index_url: string; public_key: string }): Promise<PluginCatalogSource> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/sources`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Marketplace source registration failed.');
    return data;
  },

  async setMarketplaceSource(sourceId: string, enabled: boolean): Promise<PluginCatalogSource> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/sources/${encodeURIComponent(sourceId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Marketplace source update failed.');
    return data;
  },

  async removeMarketplaceSource(sourceId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
    if (!res.ok) { const data = await res.json(); throw new Error(data?.detail?.message || 'Marketplace source removal failed.'); }
  },

  async refreshMarketplaceSource(sourceId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/sources/${encodeURIComponent(sourceId)}/refresh`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Marketplace source refresh failed.');
    return data;
  },

  async browseMarketplace(): Promise<MarketplacePlugin[]> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/catalog`);
    return res.json();
  },

  async browseMarketplaceBenchmarkPacks(): Promise<MarketplaceBenchmarkPack[]> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/benchmark-packs`);
    return res.json();
  },

  async importMarketplaceBenchmarkPack(payload: { source_id: string; pack_id: string; version: string; approval_id: string }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/benchmark-packs/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Benchmark pack import failed.');
    return data;
  },

  async browseMarketplaceWorkflowTemplates(): Promise<MarketplaceWorkflowTemplate[]> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/workflow-templates`);
    return res.json();
  },

  async importMarketplaceWorkflowTemplate(payload: { source_id: string; template_id: string; version: string; approval_id: string }): Promise<any> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/workflow-templates/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Workflow template import failed.');
    return data;
  },

  async installMarketplacePlugin(payload: { source_id: string; plugin_id: string; version: string; granted_permissions: string[]; permission_profile: string; approval_id: string }): Promise<PluginRecord> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/install`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Marketplace plugin install failed.');
    return data;
  },

  async rollbackMarketplacePlugin(pluginId: string, approvalId: string): Promise<PluginRecord> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/${encodeURIComponent(pluginId)}/rollback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approval_id: approvalId }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || 'Marketplace plugin rollback failed.');
    return data;
  },

  async removeMarketplacePlugin(pluginId: string, approvalId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/plugins/marketplace/${encodeURIComponent(pluginId)}/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approval_id: approvalId }) });
    if (!res.ok) { const data = await res.json(); throw new Error(data?.detail?.message || 'Marketplace plugin removal failed.'); }
  },

  async inspectPlugin(folderPath: string): Promise<PluginInspection> {
    const res = await fetch(`${API_BASE}/api/plugins/inspect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder_path: folderPath }) });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Plugin inspection failed.');
    return data;
  },

  async registerPlugin(folderPath: string, grantedPermissions: string[], permissionProfile: string = 'developer'): Promise<PluginRecord> {
    const res = await fetch(`${API_BASE}/api/plugins/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder_path: folderPath, granted_permissions: grantedPermissions, permission_profile: permissionProfile }) });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Plugin registration failed.');
    return data;
  },

  async getLeaderboard(category: string = "all"): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/benchmarks/leaderboard?category=${category}`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  },

  async listBenchmarks(): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/benchmarks`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  },

  async listBenchmarkSuiteVersions(suiteKey: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/benchmarks/suites/${encodeURIComponent(suiteKey)}/versions`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  },

  async listBenchmarkCases(versionId: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/benchmarks/versions/${encodeURIComponent(versionId)}/cases`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  },

  async runRealBenchmark(suiteVersionId: string, agentId: string, workspaceId: string, timeoutSeconds: number = 120): Promise<any> {
    const res = await fetch(`${API_BASE}/api/benchmarks/run-real`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suite_version_id: suiteVersionId, agent_id: agentId, workspace_id: workspaceId, timeout_seconds: timeoutSeconds }),
    });
    return res.json();
  },

  async runBenchmark(benchmarkId: string, modelIds: string[]): Promise<any> {
    const res = await fetch(`${API_BASE}/api/benchmarks/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ benchmark_id: benchmarkId, model_ids: modelIds }),
    });
    return res.json();
  },

  async getBlindPair(prompt?: string): Promise<any> {
    const url = prompt ? `${API_BASE}/api/arena/pair?prompt=${encodeURIComponent(prompt)}` : `${API_BASE}/api/arena/pair`;
    const res = await fetch(url);
    return res.json();
  },

  async submitArenaVote(payload: any): Promise<any> {
    const res = await fetch(`${API_BASE}/api/arena/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  async listSkills(): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/skills`);
    return res.json();
  },

  async importSkillsFolder(folderPath: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/skills/import-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folderPath }),
    });
    return res.json();
  },

  async runSkill(skillId: string, taskInput: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/skills/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_id: skillId, task_input: taskInput }),
    });
    return res.json();
  },

  async listWorkflows(): Promise<any[]> {
    const res = await fetch(`${API_BASE}/api/workflows`);
    return res.json();
  },

  async runWorkflow(workflowId: string, inputText: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/workflows/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow_id: workflowId, input_text: inputText }),
    });
    return res.json();
  },

  async getSecrets(): Promise<any> {
    const res = await fetch(`${API_BASE}/api/secrets`);
    return res.json();
  },

  async setSecret(provider: string, keyValue: string): Promise<any> {
    const res = await fetch(`${API_BASE}/api/secrets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, key_value: keyValue }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Credential verification failed.');
    return data;
  },

  async getSettings(): Promise<Record<string, any>> {
    const res = await fetch(`${API_BASE}/api/settings`);
    const data = await res.json();
    return data.settings;
  },

  async updateSettings(settings: Record<string, string | number | boolean>): Promise<any> {
    const res = await fetch(`${API_BASE}/api/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail?.message || data?.detail || 'Settings update failed.');
    return data;
  },
};
