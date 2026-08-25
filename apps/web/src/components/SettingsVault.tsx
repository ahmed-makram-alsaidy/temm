import React, { useEffect, useState } from 'react';
import {
  Check,
  CheckCircle2,
  Languages,
  LockKeyhole,
  Moon,
  Palette,
  Plug,
  Route,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  WalletCards,
} from 'lucide-react';
import type { Model } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { useTheme } from '../theme/ThemeContext';
import { StateNotice } from './StateNotice';

type SettingsTab = 'general' | 'connections' | 'routing' | 'appearance' | 'security' | 'billing';

interface SettingsVaultProps { onRestartSetup?: () => void }

const readPreferences = () => {
  try { return JSON.parse(localStorage.getItem('ai_fleet_preferences') || '{}'); }
  catch { return {}; }
};

const executableConnections = new Set(['openai', 'anthropic', 'google', 'deepseek', 'groq', 'ollama_host']);

const Toggle: React.FC<{ value: boolean; onChange: () => void; label: string }> = ({ value, onChange, label }) => (
  <button type="button" className={`switch ${value ? 'on' : ''}`} onClick={onChange} aria-label={label} aria-pressed={value} />
);

export const SettingsVault: React.FC<SettingsVaultProps> = ({ onRestartSetup }) => {
  const { isArabic, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  const savedPreferences = readPreferences();
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => {
    const requested = localStorage.getItem('ai_fleet_settings_tab') as SettingsTab | null;
    localStorage.removeItem('ai_fleet_settings_tab');
    return requested && ['general', 'connections', 'routing', 'appearance', 'security', 'billing'].includes(requested) ? requested : 'general';
  });
  const [secrets, setSecrets] = useState<Record<string, any>>({});
  const [models, setModels] = useState<Model[]>([]);
  const [selectedBaseline, setSelectedBaseline] = useState('gpt-4o');
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [keyValue, setKeyValue] = useState('');
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [verifyingProvider, setVerifyingProvider] = useState<string | null>(null);
  const [monthlyBudget, setMonthlyBudget] = useState(savedPreferences.monthlyBudget || '100');
  const [budgetWarning, setBudgetWarning] = useState(savedPreferences.budgetWarning || '80');
  const [autoScan, setAutoScan] = useState(savedPreferences.autoScan ?? true);
  const [notifications, setNotifications] = useState(savedPreferences.notifications ?? true);
  const [startOnDashboard, setStartOnDashboard] = useState(savedPreferences.startOnDashboard ?? true);
  const [freeFirst, setFreeFirst] = useState(savedPreferences.freeFirst ?? true);
  const [autoFallback, setAutoFallback] = useState(savedPreferences.autoFallback ?? true);
  const [commandApproval, setCommandApproval] = useState(savedPreferences.commandApproval ?? true);
  const [anonymousTelemetry, setAnonymousTelemetry] = useState(savedPreferences.anonymousTelemetry ?? false);
  const [compactNav, setCompactNav] = useState(savedPreferences.compactNav ?? false);
  const [reduceMotion, setReduceMotion] = useState(savedPreferences.reduceMotion ?? false);
  const [equivalentApiValue, setEquivalentApiValue] = useState(savedPreferences.equivalentApiValue ?? true);
  const [defaultRoutingMode, setDefaultRoutingMode] = useState(savedPreferences.defaultRoutingMode || 'balanced');

  const loadData = async () => {
    try {
      const [secretData, modelData, systemSettings] = await Promise.all([api.getSecrets(), api.listModels(), api.getSettings()]);
      setSecrets(secretData);
      setModels(modelData);
      const baseline = modelData.find((model) => model.is_reference_baseline);
      if (baseline) setSelectedBaseline(baseline.id);
      if (systemSettings.monthly_ai_budget) setMonthlyBudget(systemSettings.monthly_ai_budget);
      if (systemSettings.budget_alert_threshold) setBudgetWarning(systemSettings.budget_alert_threshold);
      if (systemSettings.default_routing_strategy) setDefaultRoutingMode(systemSettings.default_routing_strategy);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    localStorage.setItem('ai_fleet_preferences', JSON.stringify({ monthlyBudget, budgetWarning, autoScan, notifications, startOnDashboard, freeFirst, autoFallback, commandApproval, anonymousTelemetry, compactNav, reduceMotion, equivalentApiValue, defaultRoutingMode }));
    document.documentElement.dataset.compactNav = compactNav ? 'true' : 'false';
    document.documentElement.dataset.reduceMotion = reduceMotion ? 'true' : 'false';
  }, [monthlyBudget, budgetWarning, autoScan, notifications, startOnDashboard, freeFirst, autoFallback, commandApproval, anonymousTelemetry, compactNav, reduceMotion, equivalentApiValue, defaultRoutingMode]);

  const confirmPreferencesSaved = async () => {
    try {
      await api.updateSettings({ monthly_ai_budget: monthlyBudget, budget_alert_threshold: budgetWarning, default_routing_strategy: defaultRoutingMode });
      setSaveSuccess('preferences');
      window.setTimeout(() => setSaveSuccess(null), 1800);
    } catch (error) { console.error(error); }
  };

  const handleSaveSecret = async (provider: string) => {
    if (!keyValue.trim()) return;
    setConnectionError(null); setVerifyingProvider(provider);
    try {
      await api.setSecret(provider, keyValue.trim());
      setEditingProvider(null);
      setKeyValue('');
      setSaveSuccess(provider);
      window.setTimeout(() => setSaveSuccess(null), 2500);
      await loadData();
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : (isArabic ? 'فشل التحقق من بيانات الاتصال.' : 'Credential verification failed.'));
    } finally { setVerifyingProvider(null); }
  };

  const handleSetBaseline = async (modelId: string) => {
    setSelectedBaseline(modelId);
    try { await api.setReferenceBaseline(modelId); } catch (error) { console.error(error); }
  };

  const tabs = [
    { id: 'general' as const, ar: 'عام', en: 'General', icon: SlidersHorizontal },
    { id: 'connections' as const, ar: 'الاتصالات والمفاتيح', en: 'Connections', icon: Plug },
    { id: 'routing' as const, ar: 'التوجيه والموديلات', en: 'Routing & models', icon: Route },
    { id: 'appearance' as const, ar: 'المظهر', en: 'Appearance', icon: Palette },
    { id: 'security' as const, ar: 'الأمان والخصوصية', en: 'Security & privacy', icon: ShieldCheck },
    { id: 'billing' as const, ar: 'الميزانية والتكلفة', en: 'Budget & cost', icon: WalletCards },
  ];

  const Section: React.FC<{ title: string; description: string; children: React.ReactNode }> = ({ title, description, children }) => (
    <section className="settings-section">
      <div className="settings-section-head"><h2>{title}</h2><p>{description}</p></div>
      {children}
    </section>
  );

  const Row: React.FC<{ title: string; description: string; children: React.ReactNode }> = ({ title, description, children }) => (
    <div className="settings-row">
      <div className="settings-row-copy"><div className="settings-row-title">{title}</div><div className="settings-row-desc">{description}</div></div>
      <div className="settings-control">{children}</div>
    </div>
  );

  return (
    <div className="settings-page">
      <div className="settings-page-head">
        <div>
          <h1>{isArabic ? 'الإعدادات' : 'Settings'}</h1>
          <p>{isArabic ? 'خصص تجربة TEMM، الاتصالات، التوجيه، والخصوصية من مكان واحد.' : 'Control your TEMM experience, connections, routing, and privacy.'}</p>
        </div>
        <span className="fleet-badge badge-emerald"><LockKeyhole size={11} /> {isArabic ? 'محلي ومشفّر' : 'Local & encrypted'}</span>
      </div>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label={isArabic ? 'أقسام الإعدادات' : 'Settings sections'}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button type="button" key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)}>
                <Icon size={14} /><span>{isArabic ? tab.ar : tab.en}</span>
              </button>
            );
          })}
        </nav>

        <div className="settings-content">
          {activeTab === 'general' && (
            <>
              <Section title={isArabic ? 'تفضيلات التطبيق' : 'App preferences'} description={isArabic ? 'الإعدادات الأساسية لتجربة الاستخدام.' : 'Your everyday TEMM behavior.'}>
                <Row title={isArabic ? 'لغة الواجهة' : 'Interface language'} description={isArabic ? 'غيّر اللغة والاتجاه فورًا.' : 'Switch language and reading direction instantly.'}>
                  <div className="settings-control inline">
                    <Languages size={14} color="var(--text-muted)" />
                    <select aria-label={isArabic ? 'لغة الواجهة' : 'Interface language'} className="input-text" value={isArabic ? 'ar' : 'en'} onChange={(event) => setLanguage(event.target.value as 'ar' | 'en')}>
                      <option value="ar">العربية</option><option value="en">English</option>
                    </select>
                  </div>
                </Row>
                <Row title={isArabic ? 'ابدأ من مركز القيادة' : 'Open on command center'} description={isArabic ? 'اجعل لوحة القيادة الصفحة الأولى عند التشغيل.' : 'Use the command center as the default start screen.'}>
                  <div className="settings-control inline"><Toggle value={startOnDashboard} onChange={() => setStartOnDashboard(!startOnDashboard)} label="Start on dashboard" /></div>
                </Row>
                <Row title={isArabic ? 'فحص الأدوات تلقائيًا' : 'Auto-discover AI tools'} description={isArabic ? 'اكتشف CLIs والموديلات المحلية عند بدء التطبيق.' : 'Scan for local CLIs and models when the app starts.'}>
                  <div className="settings-control inline"><Toggle value={autoScan} onChange={() => setAutoScan(!autoScan)} label="Auto scan" /></div>
                </Row>
                <Row title={isArabic ? 'إشعارات سطح المكتب' : 'Desktop notifications'} description={isArabic ? 'تنبيهات عند اكتمال المهام أو الحاجة لتدخل.' : 'Get notified when runs finish or need attention.'}>
                  <div className="settings-control inline"><Toggle value={notifications} onChange={() => setNotifications(!notifications)} label="Notifications" /></div>
                </Row>
              </Section>
            </>
          )}

          {activeTab === 'connections' && (
            <Section title={isArabic ? 'مزودات الذكاء الاصطناعي' : 'AI provider connections'} description={isArabic ? 'يتم اختبار المفتاح مع المزود أولًا، ثم يُحفظ في خزنة النظام المحلية ولا يظهر مرة أخرى.' : 'Credentials are verified with the provider before being stored in the local OS vault.'}>
              {connectionError && <StateNotice state="error" title="Connection update failed" detail={connectionError} />}
              <div className="provider-list">
                {Object.entries(secrets).map(([provider, info]) => {
                  const supported = executableConnections.has(provider);
                  const connected = supported && info.is_configured;
                  return (
                  <div className={`provider-row ${editingProvider === provider ? 'editing' : ''}`} key={provider}>
                    <div className="provider-logo">{provider.slice(0, 2).toUpperCase()}</div>
                    <div className="provider-copy">
                      <div className="provider-name">{provider}</div>
                      <div className="provider-meta">{info.env_variable} · {info.masked_key || 'No key stored'}</div>
                    </div>
                    <div className="provider-actions">
                      <span className={`fleet-badge ${connected ? 'badge-emerald' : 'badge-muted'}`}>
                        {connected
                          ? <><Check size={10} />{isArabic ? 'متصل' : 'Connected'}</>
                          : supported
                            ? (isArabic ? 'غير متصل' : 'Not connected')
                            : (isArabic ? 'Registry فقط' : 'Registry only')}
                      </span>
                      <button type="button" className="btn-secondary" disabled={!supported} title={!supported ? (isArabic ? 'المنفّذ الحي لهذا المزود غير متاح في v0.1' : 'Live executor is not available in v0.1') : undefined} onClick={() => { setEditingProvider(editingProvider === provider ? null : provider); setKeyValue(''); }}>
                        {supported ? (editingProvider === provider ? (isArabic ? 'إلغاء' : 'Cancel') : (isArabic ? 'إعداد' : 'Configure')) : (isArabic ? 'غير متاح' : 'Unavailable')}
                      </button>
                    </div>
                    {editingProvider === provider && (
                      <div className="provider-edit">
                        <input type="password" className="input-text" value={keyValue} onChange={(event) => setKeyValue(event.target.value)} placeholder={`${provider.toUpperCase()} API key`} />
                        <button type="button" className="btn-primary" onClick={() => handleSaveSecret(provider)} disabled={!keyValue.trim() || verifyingProvider === provider}><Save size={13} />{verifyingProvider === provider ? (isArabic ? 'جارٍ التحقق…' : 'Verifying…') : (isArabic ? 'تحقق واحفظ' : 'Verify & save')}</button>
                      </div>
                    )}
                    {saveSuccess === provider && <span className="fleet-badge badge-emerald"><CheckCircle2 size={10} /> {isArabic ? 'تم التحقق والحفظ' : 'Verified & saved'}</span>}
                  </div>
                  );
                })}
              </div>
            </Section>
          )}

          {activeTab === 'routing' && (
            <>
              <Section title={isArabic ? 'استراتيجية التوجيه' : 'Routing strategy'} description={isArabic ? 'حدد كيف يوازن النظام بين الجودة والتكلفة والسرعة.' : 'Decide how TEMM balances quality, cost, and speed.'}>
                <Row title={isArabic ? 'الوضع الافتراضي' : 'Default mode'} description={isArabic ? 'يُستخدم لكل مهمة جديدة ويمكن تغييره وقت التشغيل.' : 'Applied to new tasks and can be changed per run.'}>
                  <select aria-label={isArabic ? 'وضع التوجيه الافتراضي' : 'Default routing mode'} className="input-text" value={defaultRoutingMode} onChange={(event) => setDefaultRoutingMode(event.target.value)}><option value="balanced">Balanced</option><option value="economy">Economy</option><option value="quality">Maximum quality</option><option value="fast">Fast</option></select>
                </Row>
                <Row title={isArabic ? 'المجاني أولًا' : 'Free-first routing'} description={isArabic ? 'جرّب المجاني والمحلي قبل أي API مدفوع.' : 'Try free and local capacity before paid APIs.'}>
                  <div className="settings-control inline"><Toggle value={freeFirst} onChange={() => setFreeFirst(!freeFirst)} label="Free first" /></div>
                </Row>
                <Row title={isArabic ? 'انتقال تلقائي عند الفشل' : 'Automatic fallback'} description={isArabic ? 'انتقل للموديل التالي عند rate limit أو timeout.' : 'Move to the next model after rate limits or timeouts.'}>
                  <div className="settings-control inline"><Toggle value={autoFallback} onChange={() => setAutoFallback(!autoFallback)} label="Automatic fallback" /></div>
                </Row>
              </Section>
              <Section title={isArabic ? 'الموديل المرجعي' : 'Reference model'} description={isArabic ? 'يستخدم لحساب التكلفة التي تم تجنبها والتوفير التقديري.' : 'Used to calculate avoided cost and estimated savings.'}>
                <Row title={isArabic ? 'Baseline model' : 'Baseline model'} description={isArabic ? 'غيّر المرجع المالي لكل المقارنات.' : 'Change the financial baseline for all comparisons.'}>
                  <select aria-label={isArabic ? 'الموديل المرجعي' : 'Reference model'} className="input-text" value={selectedBaseline} onChange={(event) => handleSetBaseline(event.target.value)}>
                    {models.map((model) => <option key={model.id} value={model.id}>{model.name} · ${model.input_cost_per_m.toFixed(2)}/1M</option>)}
                  </select>
                </Row>
              </Section>
            </>
          )}

          {activeTab === 'appearance' && (
            <>
              <Section title={isArabic ? 'الثيم' : 'Theme'} description={isArabic ? 'اختر المظهر المناسب لبيئة عملك.' : 'Choose the look that fits your workspace.'}>
                <div className="settings-row">
                  <div className="settings-row-copy"><div className="settings-row-title">{isArabic ? 'نظام الألوان' : 'Color mode'}</div><div className="settings-row-desc">{isArabic ? 'الوضع الفاتح هو الافتراضي.' : 'Light mode is the product default.'}</div></div>
                  <div className="settings-control">
                    <div className="theme-cards">
                      <button type="button" className={`theme-card ${theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')}>
                        <div className="theme-preview"><div className="theme-preview-sidebar" /><div className="theme-preview-lines"><span /><span /><span /></div></div>
                        <div className="theme-name"><span>{isArabic ? 'فاتح' : 'Light'}</span>{theme === 'light' ? <Check size={12} /> : <Sun size={12} />}</div>
                      </button>
                      <button type="button" className={`theme-card ${theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')}>
                        <div className="theme-preview dark"><div className="theme-preview-sidebar" /><div className="theme-preview-lines"><span /><span /><span /></div></div>
                        <div className="theme-name"><span>{isArabic ? 'داكن' : 'Dark'}</span>{theme === 'dark' ? <Check size={12} /> : <Moon size={12} />}</div>
                      </button>
                    </div>
                  </div>
                </div>
              </Section>
              <Section title={isArabic ? 'واجهة العرض' : 'Interface'} description={isArabic ? 'تحكم في كثافة وحركة الواجهة.' : 'Tune navigation density and motion.'}>
                <Row title={isArabic ? 'تنقل مضغوط' : 'Compact navigation'} description={isArabic ? 'قلل عرض القائمة الجانبية لزيادة مساحة المحتوى.' : 'Reduce sidebar width to give content more room.'}>
                  <div className="settings-control inline"><Toggle value={compactNav} onChange={() => setCompactNav(!compactNav)} label="Compact navigation" /></div>
                </Row>
                <Row title={isArabic ? 'تقليل الحركة' : 'Reduce motion'} description={isArabic ? 'قلل الانتقالات والحركات البصرية.' : 'Minimize transitions and interface movement.'}>
                  <div className="settings-control inline"><Toggle value={reduceMotion} onChange={() => setReduceMotion(!reduceMotion)} label="Reduce motion" /></div>
                </Row>
              </Section>
            </>
          )}

          {activeTab === 'security' && (
            <>
              <div className="settings-note"><ShieldCheck size={15} color="var(--accent)" /><span>{isArabic ? 'TEMM يعمل محليًا. لا يوجد حساب إلزامي، ولا Telemetry مفروضة، والمفاتيح تُخزن في خزنة نظام التشغيل.' : 'TEMM is local-first: no mandatory account, no forced telemetry, and credentials stay in your OS vault.'}</span></div>
              <Section title={isArabic ? 'صلاحيات التنفيذ' : 'Execution permissions'} description={isArabic ? 'حواجز الأمان قبل تشغيل الأوامر والوصول للملفات.' : 'Safety controls for commands and workspace access.'}>
                <Row title={isArabic ? 'موافقة على الأوامر الخطرة' : 'Approve destructive commands'} description={isArabic ? 'اطلب تأكيدًا قبل الحذف، التثبيت، أو أوامر النظام.' : 'Require confirmation before deletion, installs, or system changes.'}>
                  <div className="settings-control inline"><Toggle value={commandApproval} onChange={() => setCommandApproval(!commandApproval)} label="Command approval" /></div>
                </Row>
                <Row title={isArabic ? 'نطاق الملفات' : 'File access scope'} description={isArabic ? 'الوكلاء يصلون لمساحة العمل الحالية فقط.' : 'Agents can access the current workspace only.'}>
                  <select aria-label="File access scope" className="input-text"><option>Current workspace only</option><option>Ask every time</option><option>Custom folders</option></select>
                </Row>
                <Row title={isArabic ? 'بيانات استخدام مجهولة' : 'Anonymous usage data'} description={isArabic ? 'مغلق افتراضيًا. لا يتم إرسال محتوى المهام.' : 'Off by default. Task content is never included.'}>
                  <div className="settings-control inline"><Toggle value={anonymousTelemetry} onChange={() => setAnonymousTelemetry(!anonymousTelemetry)} label="Anonymous telemetry" /></div>
                </Row>
              </Section>
            </>
          )}

          {activeTab === 'billing' && (
            <>
              <Section title={isArabic ? 'الميزانية الشهرية' : 'Monthly budget'} description={isArabic ? 'راقب الإنفاق ونبّه قبل تجاوز الحد.' : 'Track spend and warn before crossing your limit.'}>
                <Row title={isArabic ? 'حد الإنفاق' : 'Spending limit'} description={isArabic ? 'ميزانية كل مزودات API مجتمعة بالدولار.' : 'Combined monthly budget for all paid APIs.'}>
                  <div className="settings-control inline"><input aria-label={isArabic ? 'حد الإنفاق الشهري' : 'Monthly spending limit'} type="number" className="input-text" value={monthlyBudget} onChange={(event) => setMonthlyBudget(event.target.value)} /><button type="button" className="btn-primary" onClick={confirmPreferencesSaved}>{saveSuccess === 'preferences' ? <Check size={13} /> : <Save size={13} />}{saveSuccess === 'preferences' ? (isArabic ? 'تم الحفظ' : 'Saved') : (isArabic ? 'حفظ' : 'Save')}</button></div>
                </Row>
                <Row title={isArabic ? 'تنبيه عند' : 'Warning threshold'} description={isArabic ? 'النسبة التي يظهر عندها تحذير الميزانية.' : 'Budget percentage that triggers a warning.'}>
                  <div className="settings-control inline"><input aria-label={isArabic ? 'حد تحذير الميزانية' : 'Budget warning threshold'} type="number" className="input-text" value={budgetWarning} onChange={(event) => setBudgetWarning(event.target.value)} /><span className="fleet-badge badge-muted">%</span></div>
                </Row>
              </Section>
              <Section title={isArabic ? 'طريقة حساب التوفير' : 'Savings methodology'} description={isArabic ? 'اختر كيف يقارن النظام تكلفة أسطولك.' : 'Choose how TEMM compares the cost of your usage.'}>
                <Row title={isArabic ? 'القيمة المكافئة للـAPI' : 'Equivalent API value'} description={isArabic ? 'اعرض قيمة استخدام الاشتراكات كتقدير، وليس كتوفير نقدي.' : 'Show subscription usage as estimated value, not direct cash savings.'}>
                  <div className="settings-control inline"><Toggle value={equivalentApiValue} onChange={() => setEquivalentApiValue(!equivalentApiValue)} label="Equivalent API value" /></div>
                </Row>
              </Section>
              {onRestartSetup && <Section title={isArabic ? 'إعداد مساحة العمل' : 'Workspace setup'} description={isArabic ? 'أعد رحلة الاكتشاف والاتصالات والتفضيلات.' : 'Rerun discovery, connections, and operating defaults.'}><Row title={isArabic ? 'تشغيل الإعداد مرة أخرى' : 'Run setup again'} description={isArabic ? 'لن يتم حذف الأدوات أو المفاتيح الحالية.' : 'Existing tools and keys will not be removed.'}><button type="button" className="btn-secondary" onClick={onRestartSetup}>{isArabic ? 'بدء الإعداد' : 'Start setup'}</button></Row></Section>}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
