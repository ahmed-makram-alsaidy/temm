import React, { useEffect, useState } from 'react';
import { Bot, Check, Cloud, Cpu, FolderDown, Plus, Search, ShieldCheck, Sparkles, Terminal, TestTube2, Zap } from 'lucide-react';
import type { Agent, MarketplaceBenchmarkPack, MarketplacePlugin, MarketplaceWorkflowTemplate, Model, PluginCatalogSource, PluginInspection, PluginRecord, ProviderInstance } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { AgentDetail } from './AgentDetail';
import { ModelCard } from './ModelCard';
import { ProviderDetail } from './ProviderDetail';
import { StateNotice } from './StateNotice';

type FleetTab = 'all' | 'models' | 'agents' | 'providers' | 'skills' | 'plugins' | 'marketplace' | 'connect';
type ConnectMethod = 'detect' | 'custom' | 'plugin';
const executableProviders = new Set(['openai', 'anthropic', 'google', 'deepseek', 'groq']);

export const FleetManager: React.FC = () => {
  const { isArabic } = useLanguage();
  const [tab, setTab] = useState<FleetTab>('all');
  const [models, setModels] = useState<Model[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<any[]>([]);
  const [connections, setConnections] = useState<Record<string, any>>({});
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [providerInstances, setProviderInstances] = useState<ProviderInstance[]>([]);
  const [query, setQuery] = useState('');
  const [connectMethod, setConnectMethod] = useState<ConnectMethod>('detect');
  const [scanning, setScanning] = useState(false);
  const [scanMessage, setScanMessage] = useState('');
  const [scanTools, setScanTools] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const [versionCommand, setVersionCommand] = useState('');
  const [workspaceFormat, setWorkspaceFormat] = useState('{prompt}');
  const [healthArgs, setHealthArgs] = useState('');
  const [environmentRefs, setEnvironmentRefs] = useState('');
  const [probeTimeout, setProbeTimeout] = useState(3);
  const [workingDirectory, setWorkingDirectory] = useState('workspace');
  const [authRequired, setAuthRequired] = useState(false);
  const [authMethod, setAuthMethod] = useState('none');
  const [authInstructions, setAuthInstructions] = useState('');
  const [inputMethod, setInputMethod] = useState('argument');
  const [outputMethod, setOutputMethod] = useState('stdout');
  const [supportsPty, setSupportsPty] = useState(false);
  const [supportsInteractive, setSupportsInteractive] = useState(false);
  const [capabilities, setCapabilities] = useState<string[]>(['coding']);
  const [testingCli, setTestingCli] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; output: string } | null>(null);
  const [pluginPath, setPluginPath] = useState('');
  const [pluginMessage, setPluginMessage] = useState('');
  const [pluginInspection, setPluginInspection] = useState<PluginInspection | null>(null);
  const [pluginPermissionsAccepted, setPluginPermissionsAccepted] = useState(false);
  const [pluginTestResults, setPluginTestResults] = useState<Record<string, any>>({});
  const [marketplaceSources, setMarketplaceSources] = useState<PluginCatalogSource[]>([]);
  const [marketplaceEntries, setMarketplaceEntries] = useState<MarketplacePlugin[]>([]);
  const [marketplaceBenchmarkPacks, setMarketplaceBenchmarkPacks] = useState<MarketplaceBenchmarkPack[]>([]);
  const [marketplaceWorkflowTemplates, setMarketplaceWorkflowTemplates] = useState<MarketplaceWorkflowTemplate[]>([]);
  const [marketplaceMessage, setMarketplaceMessage] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceKey, setSourceKey] = useState('');
  const [agentActionError, setAgentActionError] = useState('');
  const [registryLoading, setRegistryLoading] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<ProviderInstance | null>(null);

  const load = async () => {
    const results = await Promise.allSettled([api.listModels(), api.listAgents(), api.listSkills(), api.getSecrets(), api.listPlugins(), api.listProviderInstances(), api.listMarketplaceSources(), api.browseMarketplace(), api.browseMarketplaceBenchmarkPacks(), api.browseMarketplaceWorkflowTemplates()]);
    const setters = [setModels, setAgents, setSkills, setConnections, setPlugins, setProviderInstances, setMarketplaceSources, setMarketplaceEntries, setMarketplaceBenchmarkPacks, setMarketplaceWorkflowTemplates] as Array<(value: any) => void>;
    results.forEach((result, index) => { if (result.status === 'fulfilled') setters[index](result.value); });
    const failure = results.find((result) => result.status === 'rejected');
    if (failure?.status === 'rejected') { console.error(failure.reason); setAgentActionError(failure.reason instanceof Error ? failure.reason.message : 'Some fleet data could not be loaded.'); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (tab !== 'providers' && tab !== 'agents') return;
    let active = true;
    const request = tab === 'providers' ? api.listProviderInstances : api.listAgents;
    const apply = tab === 'providers' ? setProviderInstances : setAgents;
    const refresh = async () => {
      setRegistryLoading(true); setAgentActionError('');
      try {
        let lastError: unknown;
        for (let attempt = 0; attempt < 2; attempt += 1) {
          try { const records = await request(); if (active) apply(records as any); return; }
          catch (reason) { lastError = reason; if (attempt === 0) await new Promise((resolve) => window.setTimeout(resolve, 250)); }
        }
        throw lastError;
      } catch (reason) { if (active) setAgentActionError(reason instanceof Error ? reason.message : 'Registry data could not be loaded.'); }
      finally { if (active) setRegistryLoading(false); }
    };
    void refresh();
    return () => { active = false; };
  }, [tab]);

  const selectTab = (next: FleetTab) => {
    setTab(next);
    if (next === 'providers') api.listProviderInstances().then(setProviderInstances).catch((reason) => setAgentActionError(reason instanceof Error ? reason.message : 'Providers could not be loaded.'));
    if (next === 'marketplace' || next === 'plugins') void load();
  };

  const matches = (value: string) => value.toLowerCase().includes(query.toLowerCase());
  const visibleModels = models.filter((model) => matches(`${model.name} ${model.provider} ${model.category}`));
  const visibleAgents = agents.filter((agent) => matches(`${agent.name} ${agent.description} ${agent.tool_kind} ${agent.discovery_state} ${agent.capabilities.join(' ')}`));
  const providerConfigured = (provider: string) => {
    const normalized = provider === 'gemini' ? 'google' : provider === 'claude' ? 'anthropic' : provider;
    return normalized === 'ollama' ? false : executableProviders.has(normalized) && !!connections[normalized]?.is_configured;
  };
  const modelExecutable = (model: Model) => model.is_active && model.lifecycle_status === 'active' && model.availability_state === 'available' && !!model.availability_checked_at;
  const connectedProviderCount = Object.entries(connections).filter(([provider, item]) => executableProviders.has(provider) && item.is_configured).length;

  const scan = async () => {
    setScanning(true); setScanMessage('');
    try {
      const result = await api.triggerScan();
      const discovered = result?.discovered_tools || [];
      const count = result?.total_discovered ?? discovered.length;
      const verified = result?.summary?.verified ?? 0;
      setScanTools(discovered);
      setScanMessage(isArabic ? `اكتمل الفحص: ${verified} موثقة من ${count} أداة مكتشفة.` : `Scan complete: ${verified} verified of ${count} detected tools.`);
      await load();
    } catch (error) { console.error(error); setScanMessage(isArabic ? 'تعذر إكمال الفحص.' : 'The scan could not be completed.'); }
    finally { setScanning(false); }
  };

  const parseArgs = (value: string) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);

  const addCli = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !command.trim()) return;
    try {
      await api.addAgent({ name: name.trim(), executable: command.trim(), version_probe_args: parseArgs(versionCommand), health_probe_args: parseArgs(healthArgs), invocation_args: parseArgs(workspaceFormat), input_method: inputMethod, output_method: outputMethod, working_directory: workingDirectory, supports_pty: supportsPty, supports_interactive: supportsPty && supportsInteractive, capabilities, environment_refs: parseArgs(environmentRefs), probe_timeout_seconds: probeTimeout, auth_required: authRequired, auth_method: authRequired ? authMethod : 'none', auth_setup_instructions: authInstructions });
      setName(''); setCommand(''); setVersionCommand(''); setHealthArgs(''); setEnvironmentRefs(''); setTestResult(null); await load(); setTab('agents');
    } catch (reason) { setTestResult({ success: false, output: reason instanceof Error ? reason.message : 'Could not save this CLI.' }); }
  };

  const testCli = async () => {
    if (!command.trim()) return;
    setTestingCli(true); setTestResult(null);
    try {
      const result = await api.inspectAgent({ executable: command.trim(), version_probe_args: parseArgs(versionCommand), timeout_seconds: probeTimeout });
      setTestResult({ success: result.state === 'verified' || result.state === 'detected', output: `${result.state.toUpperCase()}${result.version ? ` · ${result.version}` : ''}${result.evidence?.reason ? ` · ${result.evidence.reason}` : ''}` });
    } catch (error) { console.error(error); setTestResult({ success: false, output: isArabic ? 'تعذر تشغيل أمر الاختبار.' : 'Could not run the test command.' }); }
    finally { setTestingCli(false); }
  };

  const toggleCapability = (capability: string) => setCapabilities((current) => current.includes(capability) ? current.filter((item) => item !== capability) : [...current, capability]);

  const toggleAgent = async (agent: Agent) => {
    setAgentActionError('');
    try { await api.updateAgent(agent.id, { expected_revision: agent.revision, user_enabled: !agent.user_enabled }); await load(); }
    catch (reason) { setAgentActionError(reason instanceof Error ? reason.message : 'Agent update failed.'); }
  };

  const removeAgent = async (agent: Agent) => {
    const confirmed = window.confirm(isArabic ? `إزالة ${agent.name}؟ سيُحفظ سجل التشغيل السابق.` : `Remove ${agent.name}? Existing run history will be preserved.`);
    if (!confirmed) return;
    setAgentActionError('');
    try { await api.deleteAgent(agent.id); await load(); }
    catch (reason) { setAgentActionError(reason instanceof Error ? reason.message : 'Agent removal failed.'); }
  };

  const inspectPlugin = async () => {
    if (!pluginPath.trim()) return;
    setPluginMessage(''); setPluginInspection(null); setPluginPermissionsAccepted(false);
    try {
      const inspection = await api.inspectPlugin(pluginPath.trim());
      setPluginInspection(inspection);
      setPluginMessage(inspection.valid ? (isArabic ? 'الحزمة صالحة للتسجيل. راجع الصلاحيات أولًا.' : 'Package is valid for registration. Review permissions first.') : (isArabic ? 'الحزمة ناقصة ولا يمكن تسجيلها.' : 'Package is incomplete and cannot be registered.'));
    } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Inspection failed.'); }
  };

  const registerPlugin = async () => {
    if (!pluginInspection?.valid) return;
    try {
      await api.registerPlugin(pluginInspection.folder_path, pluginPermissionsAccepted ? pluginInspection.permissions : []);
      setPluginMessage(isArabic ? 'تم تسجيل الـPlugin بدون تشغيل كوده.' : 'Plugin registered without executing its code.');
      setPluginInspection(null); setPluginPath(''); await load(); setTab('plugins');
    } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Registration failed.'); }
  };

  const addMarketplaceSource = async () => {
    setMarketplaceMessage('');
    try {
      await api.addMarketplaceSource({ source_id: sourceId.trim(), index_url: sourceUrl.trim(), public_key: sourceKey.trim() });
      setSourceId(''); setSourceUrl(''); setSourceKey(''); await load();
      setMarketplaceMessage(isArabic ? 'تمت إضافة المصدر معطلًا. فعّله صراحةً ثم حدّثه.' : 'Source added disabled. Explicitly enable it, then refresh.');
    } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Source registration failed.'); }
  };

  const installMarketplacePlugin = async (entry: MarketplacePlugin) => {
    const permissionList = entry.permissions.length ? entry.permissions.join(', ') : 'none';
    if (!window.confirm(isArabic ? `تثبيت ${entry.manifest.name}؟ الصلاحيات: ${permissionList}. التوقيع لا يعني أن الكود موثوق.` : `Install ${entry.manifest.name}? Permissions: ${permissionList}. A valid catalog signature does not make plugin code trusted.`)) return;
    setMarketplaceMessage('');
    try {
      const scopeId = `${entry.source_id}:${entry.manifest.id}:${entry.manifest.version}`;
      const approval = await api.requestApproval({ action_type: 'network', scope_type: 'plugin_install', scope_id: scopeId, summary: `Install ${entry.manifest.name} ${entry.manifest.version}`, details: { source_id: entry.source_id, permissions: entry.permissions, package_sha256: entry.package.sha256 } });
      await api.decideApproval(approval.id, true, 'Approved from marketplace permission review.');
      await api.installMarketplacePlugin({ source_id: entry.source_id, plugin_id: entry.manifest.id, version: entry.manifest.version, granted_permissions: entry.permissions, permission_profile: 'developer', approval_id: approval.id });
      await load(); setMarketplaceMessage(isArabic ? 'تم التثبيت بعد التحقق من التوقيع والبصمة والصلاحيات.' : 'Installed after signature, hash, and permission verification.');
    } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Marketplace install failed.'); }
  };

  const importMarketplaceBenchmarkPack = async (pack: MarketplaceBenchmarkPack) => {
    if (!window.confirm(isArabic ? `استيراد ${pack.pack.name}؟ المحتوى غير تنفيذي لكنه سيضيف حالات Benchmark محلية.` : `Import ${pack.pack.name}? Content is non-executable but will add local benchmark cases.`)) return;
    try {
      const scopeId = `${pack.source_id}:${pack.identity.id}:${pack.identity.version}`;
      const approval = await api.requestApproval({ action_type: 'network', scope_type: 'benchmark_pack_import', scope_id: scopeId, summary: `Import ${pack.pack.name}`, details: { source_id: pack.source_id, sha256: pack.package.sha256 } });
      await api.decideApproval(approval.id, true, 'Approved signed benchmark pack import.');
      await api.importMarketplaceBenchmarkPack({ source_id: pack.source_id, pack_id: pack.identity.id, version: pack.identity.version, approval_id: approval.id });
      setMarketplaceMessage(isArabic ? 'تم استيراد حزمة Benchmark مع مصدرها وبصمتها.' : 'Benchmark pack imported with source and hash provenance.');
    } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Benchmark pack import failed.'); }
  };

  const importMarketplaceWorkflowTemplate = async (template: MarketplaceWorkflowTemplate) => {
    if (!window.confirm(isArabic ? `استيراد ${template.template.name}؟ لن تصبح قابلة للتنفيذ حتى تتحقق المتطلبات.` : `Import ${template.template.name}? It will remain non-executable until prerequisites are satisfied.`)) return;
    try {
      const scopeId = `${template.source_id}:${template.identity.id}:${template.identity.version}`;
      const approval = await api.requestApproval({ action_type: 'network', scope_type: 'workflow_template_import', scope_id: scopeId, summary: `Import ${template.template.name}`, details: { prerequisites: template.template.prerequisites, gate_ids: template.template.gate_ids, sha256: template.package.sha256 } });
      await api.decideApproval(approval.id, true, 'Approved signed workflow template import.');
      await api.importMarketplaceWorkflowTemplate({ source_id: template.source_id, template_id: template.identity.id, version: template.identity.version, approval_id: approval.id });
      setMarketplaceMessage(isArabic ? 'تم استيراد القالب كتعريف غير تنفيذي مع متطلباته.' : 'Workflow template imported as a non-executable definition with prerequisites.');
    } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Workflow template import failed.'); }
  };

  const rollbackMarketplacePlugin = async (plugin: PluginRecord) => {
    if (!window.confirm(isArabic ? `الرجوع إلى النسخة السابقة من ${plugin.name}؟` : `Roll back ${plugin.name} to its retained previous version?`)) return;
    try {
      const approval = await api.requestApproval({ action_type: 'destructive', scope_type: 'plugin_rollback', scope_id: plugin.id, summary: `Roll back ${plugin.name}`, details: { current_version: plugin.version, previous_hash: plugin.previous_hash } });
      await api.decideApproval(approval.id, true, 'Approved marketplace rollback.');
      await api.rollbackMarketplacePlugin(plugin.id, approval.id); await load();
    } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Rollback failed.'); }
  };

  const removeMarketplacePlugin = async (plugin: PluginRecord) => {
    if (!window.confirm(isArabic ? `إزالة ${plugin.name} ونسخه المحتفظ بها؟` : `Remove ${plugin.name} and its retained marketplace versions?`)) return;
    try {
      const approval = await api.requestApproval({ action_type: 'destructive', scope_type: 'plugin_remove', scope_id: plugin.id, summary: `Remove ${plugin.name}`, details: { version: plugin.version, source_id: plugin.source_id } });
      await api.decideApproval(approval.id, true, 'Approved marketplace removal.');
      await api.removeMarketplacePlugin(plugin.id, approval.id); await load();
    } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Removal failed.'); }
  };

  const tabs: Array<[FleetTab, string]> = [['all', isArabic ? 'الكل' : 'All'], ['models', isArabic ? 'الموديلات' : 'Models'], ['agents', isArabic ? 'الوكلاء' : 'Agents'], ['providers', isArabic ? 'المزودات' : 'Providers'], ['skills', isArabic ? 'المهارات' : 'Skills'], ['plugins', 'Plugins'], ['marketplace', isArabic ? 'المتجر' : 'Marketplace']];

  return (
    <div className="product-page fleet-page">
      <div className="product-page-head"><div><h1>{isArabic ? 'الأدوات' : 'Tools'}</h1><p>{isArabic ? 'كل الموديلات والوكلاء والمزودات التي يمكن للنظام استخدامها.' : 'Every model, agent, and provider the system can use.'}</p></div><button type="button" className="btn-primary" onClick={() => setTab('connect')}><Plus size={14} /> {isArabic ? 'ربط أداة AI' : 'Connect AI tool'}</button></div>
      <div className="fleet-controls"><div className="tab-strip">{tabs.map(([id, label]) => <button type="button" key={id} className={tab === id ? 'active' : ''} onClick={() => void selectTab(id)}>{label}</button>)}</div>{tab !== 'connect' && <div className="compact-search"><Search size={14} /><input aria-label={isArabic ? 'بحث في الأسطول' : 'Search fleet'} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? 'بحث…' : 'Search…'} /></div>}</div>

      {tab === 'all' && (
        <>
          <section className="fleet-summary"><article><Cpu size={16} /><div><strong>{models.length}</strong><span>{isArabic ? 'موديل مسجل' : 'registered models'}</span></div></article><article><Bot size={16} /><div><strong>{agents.filter((item) => item.tool_kind === 'agent' && item.discovery_state === 'verified').length}</strong><span>{isArabic ? 'وكيل مثبت وجاهز' : 'installed ready agents'}</span></div></article><article><Cloud size={16} /><div><strong>{connectedProviderCount}</strong><span>{isArabic ? 'مزود متصل' : 'connected providers'}</span></div></article><article><Sparkles size={16} /><div><strong>{skills.length}</strong><span>{isArabic ? 'مهارة مسجلة' : 'registered skills'}</span></div></article></section>
          <section className="fleet-section"><div className="panel-heading"><div><h2>{isArabic ? 'موديلات متاحة بأدلة حديثة' : 'Models with current availability evidence'}</h2><p>{isArabic ? 'لا تكفي بيانات الاعتماد وحدها لإثبات التوافر.' : 'Credentials alone do not prove model availability.'}</p></div></div>{visibleModels.filter(modelExecutable).length ? <div className="asset-grid">{visibleModels.filter(modelExecutable).slice(0, 6).map((model) => <ModelCard key={model.id} model={model} providerConfigured={providerConfigured(model.provider)} onToggle={async () => { await api.toggleModelActive(model.id); load(); }} onBaseline={async () => { try { await api.setReferenceBaseline(model.id); await load(); } catch (reason) { setAgentActionError(reason instanceof Error ? reason.message : 'Baseline update failed.'); } }} isArabic={isArabic} />)}</div> : <StateNotice state="unknown" title={isArabic ? 'لا توجد موديلات متاحة بأدلة حالية' : 'No models have current availability evidence'} detail={isArabic ? 'قد تكون المزودات مهيأة، لكن يلزم رصد حديث للموديل قبل التنفيذ.' : 'Providers may be configured, but a current model observation is required before execution.'} />}</section>
        </>
      )}

      {tab === 'models' && <>{agentActionError && <StateNotice state="error" title="Fleet operation failed" detail={agentActionError} />}<div className="asset-grid">{visibleModels.map((model) => <ModelCard key={model.id} model={model} providerConfigured={providerConfigured(model.provider)} onToggle={async () => { await api.toggleModelActive(model.id); load(); }} onBaseline={async () => { setAgentActionError(''); try { await api.setReferenceBaseline(model.id); await load(); } catch (reason) { setAgentActionError(reason instanceof Error ? reason.message : 'Baseline update failed.'); } }} isArabic={isArabic} />)}</div></>}
      {tab === 'agents' && <>{registryLoading && <StateNotice state="loading" title={isArabic ? 'جارٍ تحميل الوكلاء' : 'Loading agents'} detail={isArabic ? 'يتم تحديث سجل الوكلاء المحلي.' : 'Refreshing the local Agent Registry.'} />}{agentActionError && <StateNotice state="error" title="Fleet operation failed" detail={agentActionError} />}<div className="asset-grid">{visibleAgents.map((agent) => <article className={`surface-card asset-card ${!agent.user_enabled || agent.lifecycle_status === 'retired' ? 'agent-disabled' : ''}`} key={agent.id} onDoubleClick={() => setSelectedAgent(agent)}><div className="asset-card-head"><div className="asset-icon"><Terminal size={17} /></div><span className={`status-badge discovery-${agent.discovery_state}`}>{agent.discovery_state}</span></div><h3>{agent.name}</h3><p>{agent.detected_path || agent.description || agent.cli_command}</p><div className="asset-tags"><span>{agent.tool_kind}</span>{agent.capabilities.slice(0, 3).map((item) => <span key={item}>{item}</span>)}{agent.supports_interactive && <span>Interactive PTY</span>}</div><div className="agent-evidence"><span>{agent.version || (isArabic ? 'لم يُتحقق من الإصدار' : 'Version not verified')}</span><small>{agent.last_checked_at ? new Date(agent.last_checked_at).toLocaleString() : (isArabic ? 'لم يُفحص بعد' : 'Not checked yet')}</small><small>Auth: {agent.auth_state} · {agent.auth_method}</small></div><div className="asset-footer"><span>{agent.discovery_source} · {agent.permission_profile} · {agent.lifecycle_status}</span><div className="agent-actions"><button type="button" onClick={() => setSelectedAgent(agent)}>{isArabic ? 'تفاصيل' : 'Details'}</button><button type="button" onClick={() => toggleAgent(agent)}>{agent.user_enabled ? (isArabic ? 'تعطيل' : 'Disable') : (isArabic ? 'تفعيل' : 'Enable')}</button>{agent.lifecycle_status !== 'retired' && <button type="button" onClick={async () => { setAgentActionError(''); try { await api.rescanAgent(agent.id); await load(); } catch (reason) { setAgentActionError(reason instanceof Error ? reason.message : 'Rescan failed.'); } }}>{isArabic ? 'إعادة الفحص' : 'Rescan'}</button>}{agent.discovery_source === 'manual' && agent.lifecycle_status !== 'retired' && <button type="button" className="danger" onClick={() => removeAgent(agent)}>{isArabic ? 'إزالة' : 'Remove'}</button>}</div></div></article>)}</div></>}
      {tab === 'providers' && (registryLoading ? <StateNotice state="loading" title={isArabic ? 'جارٍ تحميل المزودات' : 'Loading providers'} detail={isArabic ? 'يتم تحديث سجل المزودات المحلي.' : 'Refreshing the local Provider Registry.'} /> : providerInstances.length ? <div className="provider-grid">{providerInstances.filter((item) => matches(`${item.name} ${item.adapter_id} ${item.health_state}`)).map((item) => <button type="button" className="surface-card provider-card" key={item.id} onClick={() => setSelectedProvider(item)}><div className="provider-symbol">{item.name.slice(0, 2).toUpperCase()}</div><div><h3>{item.name}</h3><p>{item.adapter_id} · {item.capabilities.length} capabilities</p></div><span className={`status-badge model-${item.health_state}`}>{item.health_state}</span></button>)}</div> : <StateNotice state="empty" title={isArabic ? 'لا توجد نسخ مزودين مسجلة' : 'No provider instances registered'} detail={isArabic ? 'بيانات الاعتماد القديمة لا تُعد نسخة مزود موثقة حتى تُنقل إلى السجل.' : 'Legacy credentials are not authoritative provider instances until migrated into the registry.'} />)}
      {tab === 'skills' && <div className="asset-grid">{skills.filter((skill) => matches(`${skill.name} ${skill.description || ''}`)).map((skill) => <article className="surface-card asset-card" key={skill.id}><div className="asset-card-head"><div className="asset-icon"><Sparkles size={17} /></div><span className="status-badge completed">{isArabic ? 'متاحة' : 'Available'}</span></div><h3>{skill.name}</h3><p>{skill.description || (isArabic ? 'مهارة قابلة للاستخدام أثناء تنفيذ المهام.' : 'A skill available during task execution.')}</p></article>)}</div>}
      {tab === 'marketplace' && <div className="marketplace-layout"><section className="surface-card marketplace-sources"><div className="panel-heading"><div><h2>{isArabic ? 'مصادر المتجر' : 'Marketplace sources'}</h2><p>{isArabic ? 'كل مصدر معطل افتراضيًا ويتطلب مفتاح Ed25519 يحدده المستخدم.' : 'Every source is disabled by default and requires a user-selected Ed25519 key.'}</p></div></div><div className="marketplace-source-form"><input aria-label={isArabic ? 'معرف مصدر المتجر' : 'Marketplace source id'} className="input-text" value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="community-catalog" /><input aria-label={isArabic ? 'رابط فهرس المتجر' : 'Marketplace catalog URL'} className="input-text" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://example.com/catalog.json" /><input aria-label={isArabic ? 'مفتاح مصدر المتجر' : 'Marketplace source public key'} className="input-text font-mono" value={sourceKey} onChange={(event) => setSourceKey(event.target.value)} placeholder="Ed25519 public key (base64)" /><button type="button" className="btn-secondary" onClick={addMarketplaceSource} disabled={!sourceId.trim() || !sourceUrl.trim() || !sourceKey.trim()}>{isArabic ? 'إضافة معطلة' : 'Add disabled'}</button></div><div className="marketplace-source-list">{marketplaceSources.map((source) => <article key={source.id}><div><strong>{source.id}</strong><small>{source.index_url}</small><span>{source.last_state} · {source.entry_count} entries</span></div><div className="agent-actions"><button type="button" onClick={async () => { try { await api.setMarketplaceSource(source.id, !source.enabled); await load(); } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Source update failed.'); } }}>{source.enabled ? (isArabic ? 'تعطيل' : 'Disable') : (isArabic ? 'تفعيل' : 'Enable')}</button><button type="button" disabled={!source.enabled} onClick={async () => { try { await api.refreshMarketplaceSource(source.id); await load(); } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Refresh failed.'); } }}>{isArabic ? 'تحديث موثق' : 'Verified refresh'}</button>{!source.enabled && <button type="button" onClick={async () => { if (!window.confirm(isArabic ? `إزالة المصدر ${source.id}؟` : `Remove source ${source.id}?`)) return; try { await api.removeMarketplaceSource(source.id); await load(); } catch (reason) { setMarketplaceMessage(reason instanceof Error ? reason.message : 'Source removal failed.'); } }}>{isArabic ? 'إزالة' : 'Remove'}</button>}</div></article>)}</div></section>{marketplaceMessage && <StateNotice state={marketplaceMessage.toLowerCase().includes('fail') || marketplaceMessage.toLowerCase().includes('error') ? 'error' : 'unknown'} title={isArabic ? 'حالة المتجر' : 'Marketplace state'} detail={marketplaceMessage} />}<section><div className="panel-heading"><div><h2>{isArabic ? 'الحزم الموقعة' : 'Signed catalog packages'}</h2><p>{isArabic ? 'التوقيع يثبت سلامة الفهرس فقط. سمعة الكود تبقى غير موثقة.' : 'A signature proves catalog integrity only. Code reputation remains unverified.'}</p></div></div>{marketplaceEntries.length ? <div className="asset-grid">{marketplaceEntries.map((entry) => <article className="surface-card asset-card" key={`${entry.source_id}:${entry.manifest.id}:${entry.manifest.version}`}><div className="asset-card-head"><div className="asset-icon"><FolderDown size={17} /></div><span className={`status-badge ${entry.compatible && entry.platform_supported ? 'completed' : ''}`}>{entry.compatible && entry.platform_supported ? 'compatible' : 'unavailable'}</span></div><h3>{entry.manifest.name}</h3><p>{entry.author} · {entry.source_id}</p><div className="asset-tags"><span>v{entry.manifest.version}</span><span>{entry.manifest.type}</span><span>{entry.reputation} reputation</span></div><div className="agent-evidence"><span>Package {entry.package.sha256.slice(0, 12)}…</span><small>{entry.permissions.length ? entry.permissions.join(' · ') : 'No permissions requested'}</small><small>Catalog expires {new Date(entry.catalog_expires_at).toLocaleString()}</small></div><div className="asset-footer"><span>Explicit review required</span><button type="button" className="btn-secondary" disabled={!entry.compatible || !entry.platform_supported} onClick={() => installMarketplacePlugin(entry)}>{plugins.some((plugin) => plugin.id === entry.manifest.id) ? (isArabic ? 'تحديث' : 'Update') : (isArabic ? 'مراجعة وتثبيت' : 'Review & install')}</button></div></article>)}</div> : <StateNotice state="empty" title={isArabic ? 'لا توجد حزم موثقة' : 'No verified catalog packages'} detail={isArabic ? 'أضف مصدرًا، فعّله، ثم حدّث الفهرس الموقّع.' : 'Add a source, enable it, then refresh its signed index.'} />}</section><section><div className="panel-heading"><div><h2>{isArabic ? 'حزم Benchmark' : 'Benchmark packs'}</h2><p>{isArabic ? 'محتوى غير تنفيذي، موقّع ومحدّد الإصدار، ويُحفظ مع مصدره.' : 'Non-executable, signed, versioned content imported with source provenance.'}</p></div></div>{marketplaceBenchmarkPacks.length ? <div className="asset-grid">{marketplaceBenchmarkPacks.map((pack) => <article className="surface-card asset-card" key={`${pack.source_id}:${pack.identity.id}:${pack.identity.version}`}><div className="asset-card-head"><div className="asset-icon"><TestTube2 size={17} /></div><span className="status-badge completed">non-executable</span></div><h3>{pack.pack.name}</h3><p>{pack.author} · {pack.pack.category}</p><div className="asset-tags"><span>v{pack.pack.version}</span><span>schema {pack.pack.schema_version}</span><span>{pack.reputation} reputation</span></div><div className="agent-evidence"><span>SHA-256 {pack.package.sha256.slice(0, 12)}…</span><small>{pack.package.media_type} · {pack.package.size} bytes</small></div><div className="asset-footer"><span>{pack.source_id}</span><button type="button" className="btn-secondary" onClick={() => importMarketplaceBenchmarkPack(pack)}>{isArabic ? 'مراجعة واستيراد' : 'Review & import'}</button></div></article>)}</div> : <StateNotice state="empty" title={isArabic ? 'لا توجد حزم Benchmark' : 'No benchmark packs'} detail={isArabic ? 'لم يعلن أي مصدر مفعّل عن حزم متوافقة.' : 'No enabled source declares compatible benchmark packs.'} />}</section><section><div className="panel-heading"><div><h2>{isArabic ? 'قوالب Workflow' : 'Workflow templates'}</h2><p>{isArabic ? 'تعريفات موقعة وغير تنفيذية؛ تعرض المتطلبات والبوابات قبل الاستيراد.' : 'Signed, non-executable definitions with prerequisites and gates visible before import.'}</p></div></div>{marketplaceWorkflowTemplates.length ? <div className="asset-grid">{marketplaceWorkflowTemplates.map((template) => <article className="surface-card asset-card" key={`${template.source_id}:${template.identity.id}:${template.identity.version}`}><div className="asset-card-head"><div className="asset-icon"><Sparkles size={17} /></div><span className="status-badge">non-executable</span></div><h3>{template.template.name}</h3><p>{template.author} · v{template.template.version}</p><div className="asset-tags">{template.template.prerequisites.map((item) => <span key={item}>{item}</span>)}</div><div className="agent-evidence"><span>Gates: {template.template.gate_ids.join(' · ')}</span><small>SHA-256 {template.package.sha256.slice(0, 12)}…</small><small>{template.reputation} reputation</small></div><div className="asset-footer"><span>{template.source_id}</span><button type="button" className="btn-secondary" onClick={() => importMarketplaceWorkflowTemplate(template)}>{isArabic ? 'مراجعة واستيراد' : 'Review & import'}</button></div></article>)}</div> : <StateNotice state="empty" title={isArabic ? 'لا توجد قوالب Workflow' : 'No workflow templates'} detail={isArabic ? 'لم يعلن أي مصدر مفعّل عن قوالب متوافقة.' : 'No enabled source declares compatible workflow templates.'} />}</section></div>}
      {tab === 'plugins' && (plugins.length ? <div className="asset-grid">{plugins.map((plugin) => <article className="surface-card asset-card" key={plugin.id}><div className="asset-card-head"><div className="asset-icon"><FolderDown size={17} /></div><span className={`status-badge ${plugin.load_state === 'ready' ? 'completed' : ''}`}>{plugin.load_state}</span></div><h3>{plugin.name}</h3><p>{plugin.path}</p><div className="asset-tags"><span>{plugin.plugin_type}</span><span>v{plugin.version}</span><span>protocol {plugin.protocol_version}</span><span>{plugin.permission_profile}</span></div><div className="agent-evidence"><span>Hash {plugin.package_hash.slice(0, 12)}…</span><small>{plugin.granted_permissions.length}/{plugin.permissions.length} permissions granted</small>{pluginTestResults[plugin.id] && <small>Conformance: {pluginTestResults[plugin.id].passed ? 'PASS' : 'FAIL'} · {pluginTestResults[plugin.id].checks.length} checks</small>}</div><div className="asset-footer"><span>{plugin.status} · {plugin.load_state}</span><div className="agent-actions"><button type="button" onClick={async () => { try { await api.reloadPlugin(plugin.id); await load(); } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Reload failed.'); } }}>{isArabic ? 'إعادة تحميل' : 'Reload'}</button><button type="button" onClick={async () => { try { const result = await api.runPluginConformance(plugin.id); setPluginTestResults((current) => ({ ...current, [plugin.id]: result })); await load(); } catch (reason) { setPluginMessage(reason instanceof Error ? reason.message : 'Conformance failed.'); } }}>{isArabic ? 'اختبار' : 'Test'}</button>{plugin.source_type === 'marketplace' && plugin.previous_hash && <button type="button" onClick={() => rollbackMarketplacePlugin(plugin)}>{isArabic ? 'تراجع' : 'Rollback'}</button>}{plugin.source_type === 'marketplace' && <button type="button" onClick={() => removeMarketplacePlugin(plugin)}>{isArabic ? 'إزالة' : 'Remove'}</button>}</div></div></article>)}</div> : <div className="state-notice state-empty"><FolderDown size={20} /><strong>{isArabic ? 'لا توجد Plugins مسجلة' : 'No registered plugins'}</strong><span>{isArabic ? 'افحص حزمة محلية وراجع صلاحياتها قبل التسجيل.' : 'Inspect a local package and review its permissions before registration.'}</span><button type="button" className="btn-secondary" onClick={() => setTab('connect')}>{isArabic ? 'إضافة Plugin' : 'Add plugin'}</button></div>)}

      {tab === 'connect' && (
        <div className="connect-workspace">
          <div className="connect-methods">
            <button type="button" className={connectMethod === 'detect' ? 'active' : ''} onClick={() => setConnectMethod('detect')}><span><Zap size={17} /></span><div><strong>{isArabic ? 'اكتشاف تلقائي' : 'Auto detect'}</strong><small>{isArabic ? 'ابحث في الجهاز' : 'Scan this computer'}</small></div></button>
            <button type="button" className={connectMethod === 'custom' ? 'active' : ''} onClick={() => setConnectMethod('custom')}><span><Terminal size={17} /></span><div><strong>{isArabic ? 'Custom CLI' : 'Custom CLI'}</strong><small>{isArabic ? 'بدون برمجة' : 'No code required'}</small></div></button>
            <button type="button" className={connectMethod === 'plugin' ? 'active' : ''} onClick={() => setConnectMethod('plugin')}><span><FolderDown size={17} /></span><div><strong>{isArabic ? 'حزمة Plugin' : 'Plugin package'}</strong><small>{isArabic ? 'تكامل متقدم' : 'Advanced adapter'}</small></div></button>
          </div>

          {connectMethod === 'detect' && <section className="surface-card connect-detail"><div className="connect-detail-head"><div className="connect-icon"><Zap size={20} /></div><div><h2>{isArabic ? 'اكتشاف أدوات AI تلقائيًا' : 'Automatically discover AI tools'}</h2><p>{isArabic ? 'نفحص PATH والخدمات المحلية وحالة تسجيل الدخول بدون تثبيت أو تعديل أي برنامج.' : 'Scan PATH, local services, and sign-in status without installing or modifying software.'}</p></div></div><button type="button" className="btn-primary" onClick={scan} disabled={scanning}>{scanning ? (isArabic ? 'جارٍ الفحص…' : 'Scanning…') : (isArabic ? 'فحص الجهاز الآن' : 'Scan computer now')}</button>{scanMessage && <div className="scan-result"><ShieldCheck size={14} /> {scanMessage}</div>}{scanTools.length > 0 && <div className="detected-tool-list">{scanTools.map((tool, index) => { const ready = tool.state === 'verified'; return <div key={`${tool.id}-${index}`}><span className="tool-mini-icon">{(tool.name || tool.binary || 'AI').slice(0, 2).toUpperCase()}</span><div><strong>{tool.name || tool.id || tool.binary}</strong><code>{tool.path || tool.evidence?.reason || 'No executable found'}</code></div><span className={`status-badge ${ready ? 'completed' : ''}`}>{ready && <Check size={11} />} {tool.state}</span></div>; })}</div>}</section>}

          {connectMethod === 'custom' && <form className="surface-card cli-wizard" onSubmit={addCli}><div className="connect-detail-head"><div className="connect-icon"><Terminal size={20} /></div><div><h2>{isArabic ? 'إعداد أداة CLI مخصصة' : 'Configure a custom CLI'}</h2><p>{isArabic ? 'عرّف طريقة الاستدعاء مرة واحدة، ثم استخدم الأداة من أي مهمة.' : 'Define how the tool is called once, then use it from any task.'}</p></div></div><div className="wizard-grid"><label><span>{isArabic ? 'اسم الأداة' : 'Tool name'}</span><input className="input-text" value={name} onChange={(event) => setName(event.target.value)} placeholder="Future AI" /></label><label><span>{isArabic ? 'مسار الملف التنفيذي' : 'Executable or path'}</span><input className="input-text font-mono" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="C:\\Tools\\futureai.exe" /></label><label><span>{isArabic ? 'وسائط فحص الإصدار' : 'Version probe arguments'}</span><textarea className="input-text font-mono" value={versionCommand} onChange={(event) => setVersionCommand(event.target.value)} placeholder="--version" rows={2} /></label><label><span>{isArabic ? 'وسائط فحص الصحة' : 'Health probe arguments'}</span><textarea className="input-text font-mono" value={healthArgs} onChange={(event) => setHealthArgs(event.target.value)} placeholder="status" rows={2} /></label><label><span>{isArabic ? 'نمط الاستدعاء' : 'Invocation arguments'}</span><textarea className="input-text font-mono" value={workspaceFormat} onChange={(event) => setWorkspaceFormat(event.target.value)} placeholder={'run\n{prompt}'} rows={3} /></label><label><span>{isArabic ? 'طريقة الإدخال' : 'Input method'}</span><select className="input-text" value={inputMethod} onChange={(event) => setInputMethod(event.target.value)}><option value="argument">Command argument</option><option value="stdin">stdin</option></select></label><label><span>{isArabic ? 'طريقة الإخراج' : 'Output method'}</span><select className="input-text" value={outputMethod} onChange={(event) => setOutputMethod(event.target.value)}><option value="stdout">stdout</option><option value="json">JSON stdout</option></select></label><label><span>{isArabic ? 'مجلد العمل' : 'Working directory'}</span><select className="input-text" value={workingDirectory} onChange={(event) => setWorkingDirectory(event.target.value)}><option value="workspace">Approved workspace</option><option value="inherit">Inherit service directory</option></select></label><label><span>{isArabic ? 'مهلة الفحص' : 'Probe timeout (seconds)'}</span><input className="input-text" type="number" min="0.1" max="30" step="0.1" value={probeTimeout} onChange={(event) => setProbeTimeout(Number(event.target.value))} /></label><label><span>{isArabic ? 'مراجع متغيرات البيئة' : 'Environment variable references'}</span><textarea className="input-text font-mono" value={environmentRefs} onChange={(event) => setEnvironmentRefs(event.target.value)} placeholder="FUTUREAI_API_KEY" rows={2} /></label><label><span>{isArabic ? 'المصادقة' : 'Authentication'}</span><select className="input-text" value={authRequired ? authMethod : 'none'} onChange={(event) => { const method = event.target.value; setAuthRequired(method !== 'none'); setAuthMethod(method); }}><option value="none">Not required</option><option value="account">Account login</option><option value="api_key">API key</option><option value="account_or_api_key">Account or API key</option><option value="provider_credentials">Provider credentials</option><option value="environment">Environment</option><option value="custom">Custom</option></select></label><label><span>{isArabic ? 'تعليمات الإعداد' : 'Authentication setup instructions'}</span><textarea className="input-text" value={authInstructions} onChange={(event) => setAuthInstructions(event.target.value)} disabled={!authRequired} rows={2} /></label></div><div className="capability-picker"><span>{isArabic ? 'القدرات' : 'Capabilities'}</span><div>{['coding', 'reasoning', 'research', 'shell', 'file_read', 'file_write', 'streaming', 'stdin', 'tool_calling', 'model_selection', 'image_input'].map((item) => <button type="button" key={item} className={capabilities.includes(item) ? 'active' : ''} onClick={() => toggleCapability(item)}>{capabilities.includes(item) && <Check size={11} />}{item}</button>)}</div></div><div className="wizard-test"><button type="button" className="btn-secondary" onClick={testCli} disabled={!command.trim() || testingCli}><TestTube2 size={14} /> {testingCli ? (isArabic ? 'جارٍ الاختبار…' : 'Testing…') : (isArabic ? 'اختبار الاتصال' : 'Test connection')}</button>{testResult && <div className={testResult.success ? 'success' : 'failed'}><strong>{testResult.success ? (isArabic ? 'نجح الاختبار' : 'Test passed') : (isArabic ? 'فشل الاختبار' : 'Test failed')}</strong><code>{testResult.output}</code></div>}</div><div className="pty-options"><label><input type="checkbox" checked={supportsPty} onChange={(event) => { setSupportsPty(event.target.checked); if (!event.target.checked) setSupportsInteractive(false); }} /> PTY</label><label><input type="checkbox" checked={supportsInteractive} onChange={(event) => setSupportsInteractive(event.target.checked)} disabled={!supportsPty} /> {isArabic ? 'تفاعلية' : 'Interactive'}</label></div><div className="wizard-footer"><span>{isArabic ? 'تُحفظ أسماء متغيرات البيئة فقط؛ الأسرار تبقى في الخزنة.' : 'Only environment variable names are saved; secrets remain in the vault.'}</span><button type="submit" className="btn-primary" disabled={!name.trim() || !command.trim() || !capabilities.length}>{isArabic ? 'حفظ الأداة' : 'Save tool'}</button></div></form>}

          {connectMethod === 'plugin' && <section className="surface-card connect-detail"><div className="connect-detail-head"><div className="connect-icon"><FolderDown size={20} /></div><div><h2>{isArabic ? 'إضافة حزمة Plugin محلية' : 'Add a local plugin package'}</h2><p>{isArabic ? 'الفحص يقرأ الـmanifest والملفات فقط ولا يشغل أي كود من الحزمة.' : 'Inspection reads the manifest and file layout without executing package code.'}</p></div></div><label className="plugin-path"><span>{isArabic ? 'مسار مجلد الحزمة' : 'Plugin folder path'}</span><div><input className="input-text font-mono" value={pluginPath} onChange={(event) => { setPluginPath(event.target.value); setPluginInspection(null); }} placeholder="D:\\plugins\\my-agent" /><button type="button" className="btn-primary" onClick={inspectPlugin} disabled={!pluginPath.trim()}>{isArabic ? 'فحص الحزمة' : 'Inspect package'}</button></div></label>{pluginMessage && <div className="scan-result"><ShieldCheck size={14} /> {pluginMessage}</div>}{pluginInspection ? <div className="plugin-inspection"><div className="plugin-inspection-head"><div><strong>{pluginInspection.name}</strong><span>{pluginInspection.plugin_id} · v{pluginInspection.version} · protocol {pluginInspection.protocol_version}</span></div><span className={`status-badge ${pluginInspection.valid && pluginInspection.compatible ? 'completed' : ''}`}>{pluginInspection.valid ? (pluginInspection.compatible ? (isArabic ? 'صالحة ومتوافقة' : 'Valid & compatible') : (isArabic ? 'غير متوافقة' : 'Incompatible')) : (isArabic ? 'ناقصة' : 'Incomplete')}</span></div><div className="agent-evidence"><span>SHA-256 {pluginInspection.package_hash}</span><small>{pluginInspection.entrypoint}</small></div><div className="plugin-checklist">{Object.entries(pluginInspection.checklist).map(([item, ready]) => <span key={item} className={ready ? 'ready' : ''}>{ready && <Check size={11} />}{item}</span>)}</div><div className="plugin-permissions"><strong>{isArabic ? 'الصلاحيات المطلوبة' : 'Requested permissions'}</strong>{pluginInspection.permissions.length ? pluginInspection.permissions.map((permission) => <code key={permission}>{permission}</code>) : <span>{isArabic ? 'لم يذكر الـmanifest صلاحيات.' : 'No permissions declared.'}</span>}</div>{pluginInspection.permissions.length > 0 && <label className="command-confirm"><input type="checkbox" checked={pluginPermissionsAccepted} onChange={(event) => setPluginPermissionsAccepted(event.target.checked)} /><span>{isArabic ? 'راجعت الصلاحيات وأوافق على تسجيلها. التسجيل لا يعني تحميل الكود أو تشغيله.' : 'I reviewed these permissions and approve registration. Registration does not load or run plugin code.'}</span></label>}<button type="button" className="btn-primary" onClick={registerPlugin} disabled={!pluginInspection.valid || (pluginInspection.permissions.length > 0 && !pluginPermissionsAccepted)}>{isArabic ? 'تسجيل الـPlugin' : 'Register plugin'}</button></div> : <div className="manifest-preview"><span>Required package</span><code>manifest.yaml</code><code>adapter.py</code><code>README.md</code><code>tests/</code></div>}</section>}
        </div>
      )}
      {selectedProvider && <ProviderDetail provider={selectedProvider} onClose={() => setSelectedProvider(null)} onChanged={async () => { await load(); const refreshed = (await api.listProviderInstances()).find((item) => item.id === selectedProvider.id); if (refreshed) setSelectedProvider(refreshed); }} />}
      {selectedAgent && <AgentDetail agent={selectedAgent} isArabic={isArabic} onClose={() => setSelectedAgent(null)} onChanged={async () => { await load(); const refreshed = (await api.listAgents()).find((item) => item.id === selectedAgent.id); if (refreshed) setSelectedAgent(refreshed); }} />}
    </div>
  );
};
