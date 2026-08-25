import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Command, FolderKanban, KeyRound, Radar, SlidersHorizontal, Sparkles } from 'lucide-react';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';

interface OnboardingProps {
  onComplete: () => void;
  onOpenSettings: () => void;
  onOpenWorkspaces: () => void;
}

type ScanTool = { id?: string; name?: string; binary?: string; path?: string; version?: string; auth_status?: string; auth_message?: string };

export const Onboarding: React.FC<OnboardingProps> = ({ onComplete, onOpenSettings, onOpenWorkspaces }) => {
  const { isArabic } = useLanguage();
  const [step, setStep] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [tools, setTools] = useState<ScanTool[]>([]);
  const [configuredProviders, setConfiguredProviders] = useState(0);
  const [workspaceCount, setWorkspaceCount] = useState(0);
  const [routingMode, setRoutingMode] = useState('balanced');
  const [budget, setBudget] = useState('100');

  useEffect(() => {
    Promise.all([api.getSecrets(), api.listWorkspaces()]).then(([data, workspaces]) => { setConfiguredProviders(Object.values(data || {}).filter((item: any) => item?.is_configured).length); setWorkspaceCount(workspaces.length); }).catch(console.error);
  }, []);

  const scan = async () => {
    setScanning(true);
    try {
      const result = await api.triggerScan();
      setTools(result?.discovered_tools || []);
    } catch (error) { console.error(error); }
    finally { setScanning(false); }
  };

  const finish = async () => {
    const saved = JSON.parse(localStorage.getItem('ai_fleet_preferences') || '{}');
    localStorage.setItem('ai_fleet_preferences', JSON.stringify({ ...saved, defaultRoutingMode: routingMode, monthlyBudget: budget }));
    localStorage.setItem('ai_fleet_onboarding_complete', '1');
    try { await api.updateSettings({ default_routing_strategy: routingMode, monthly_ai_budget: budget }); } catch (error) { console.error(error); }
    onComplete();
  };

  const content = [
    <div className="onboarding-step intro" key="intro">
      <div className="onboarding-hero-mark"><Command size={27} /></div>
      <span className="onboarding-kicker">TEMM</span>
      <h1>{isArabic ? 'كل أدوات الذكاء الاصطناعي، بقرار واحد.' : 'Every AI tool, behind one decision.'}</h1>
      <p>{isArabic ? 'سنكتشف الأدوات على جهازك، نراجع الاتصالات، ثم نضبط طريقة الاختيار والتكلفة. لن يستغرق الإعداد أكثر من دقيقتين.' : 'We’ll discover local tools, review provider connections, and configure routing and cost. Setup takes about two minutes.'}</p>
      <div className="onboarding-promises"><span><Check size={13} /> {isArabic ? 'بيانات محلية' : 'Local data'}</span><span><Check size={13} /> {isArabic ? 'لا حساب إجباري' : 'No mandatory account'}</span><span><Check size={13} /> {isArabic ? 'يمكن تعديل كل شيء لاحقًا' : 'Change anything later'}</span></div>
    </div>,
    <div className="onboarding-step" key="scan">
      <div className="step-icon"><Radar size={22} /></div>
      <span className="onboarding-kicker">01 · DISCOVER</span>
      <h1>{isArabic ? 'اكتشاف أدوات جهازك' : 'Discover tools on this computer'}</h1>
      <p>{isArabic ? 'نبحث عن Codex وClaude وGemini وOllama وأدوات CLI المعروفة. لا يتم تثبيت أو تغيير أي شيء.' : 'We look for Codex, Claude, Gemini, Ollama, and known AI CLIs. Nothing is installed or changed.'}</p>
      {!tools.length ? <button type="button" className="btn-primary onboarding-primary" onClick={scan} disabled={scanning}><Radar size={15} /> {scanning ? (isArabic ? 'جارٍ الفحص…' : 'Scanning…') : (isArabic ? 'فحص الجهاز' : 'Scan computer')}</button> : <div className="discovery-results"><div className="discovery-summary"><CheckCircle2 size={18} /><div><strong>{tools.length} {isArabic ? 'أداة تم اكتشافها' : 'tools discovered'}</strong><span>{isArabic ? 'تم فحص التثبيت وتسجيل الدخول كلٌ على حدة' : 'Install and sign-in were checked separately'}</span></div></div><div className="discovery-list">{tools.slice(0, 6).map((tool, index) => <div key={`${tool.id}-${index}`}><span className="tool-mini-icon">{(tool.name || tool.binary || 'AI').slice(0, 2).toUpperCase()}</span><div><strong>{tool.name || tool.id || tool.binary}</strong><code>{tool.auth_message || tool.path || tool.version || 'Detected'}</code></div>{tool.auth_status === 'needs_auth' ? <KeyRound size={13} /> : <Check size={13} />}</div>)}</div></div>}
      <button type="button" className="quiet-link" onClick={() => setStep(2)}>{isArabic ? 'سأربط الأدوات لاحقًا' : 'I’ll connect tools later'}</button>
    </div>,
    <div className="onboarding-step" key="connect">
      <div className="step-icon"><KeyRound size={22} /></div>
      <span className="onboarding-kicker">02 · CONNECT</span>
      <h1>{isArabic ? 'راجع اتصالات المزودات' : 'Review provider connections'}</h1>
      <p>{isArabic ? 'المفاتيح اختيارية وتُحفظ في الخزنة المحلية. يمكنك البدء بالأدوات المحلية والمجانية فقط.' : 'API keys are optional and stay in the local vault. You can start with free and local tools only.'}</p>
      <div className="connection-status-card"><div><span className={`connection-ring ${configuredProviders ? 'connected' : ''}`}><KeyRound size={18} /></span><div><strong>{configuredProviders} {isArabic ? 'مزود متصل' : 'connected providers'}</strong><span>{configuredProviders ? (isArabic ? 'يمكنك المتابعة الآن' : 'You can continue now') : (isArabic ? 'لا مشكلة—يمكنك الإعداد لاحقًا' : 'That’s okay—you can configure later')}</span></div></div><button type="button" className="btn-secondary" onClick={onOpenSettings}>{isArabic ? 'إدارة المفاتيح' : 'Manage keys'}</button></div>
    </div>,
    <div className="onboarding-step" key="workspace">
      <div className="step-icon"><FolderKanban size={22} /></div>
      <span className="onboarding-kicker">03 · WORKSPACE</span>
      <h1>{isArabic ? 'حدد أين يمكن للوكلاء العمل' : 'Choose where agents may work'}</h1>
      <p>{isArabic ? 'Codex وClaude والأوامر لن تصل إلى ملفات الجهاز تلقائيًا. أضف مجلد مشروع وحدد صلاحياته.' : 'Codex, Claude, and commands never get automatic computer-wide access. Add a project folder and choose its permissions.'}</p>
      <div className="connection-status-card"><div><span className={`connection-ring ${workspaceCount ? 'connected' : ''}`}><FolderKanban size={18} /></span><div><strong>{workspaceCount} {isArabic ? 'مساحة عمل معتمدة' : 'approved workspaces'}</strong><span>{workspaceCount ? (isArabic ? 'يمكن للوكلاء العمل داخلها فقط' : 'Agents are limited to these folders') : (isArabic ? 'التنفيذ على الملفات سيظل متوقفًا' : 'File-based execution stays blocked')}</span></div></div><button type="button" className="btn-secondary" onClick={onOpenWorkspaces}>{isArabic ? 'إدارة المساحات' : 'Manage workspaces'}</button></div>
    </div>,
    <div className="onboarding-step" key="defaults">
      <div className="step-icon"><SlidersHorizontal size={22} /></div>
      <span className="onboarding-kicker">04 · DEFAULTS</span>
      <h1>{isArabic ? 'اضبط طريقة العمل' : 'Set your operating defaults'}</h1>
      <p>{isArabic ? 'هذه نقطة بداية فقط؛ يمكن تغييرها لكل مهمة.' : 'These are only defaults; every task can override them.'}</p>
      <div className="onboarding-form"><label><span>{isArabic ? 'أولوية التوجيه' : 'Routing priority'}</span><select value={routingMode} onChange={(event) => setRoutingMode(event.target.value)}><option value="balanced">{isArabic ? 'متوازن — موصى به' : 'Balanced — recommended'}</option><option value="economy">{isArabic ? 'الأقل تكلفة' : 'Lowest cost'}</option><option value="quality">{isArabic ? 'أعلى جودة' : 'Best quality'}</option><option value="fast">{isArabic ? 'أسرع نتيجة' : 'Fastest result'}</option></select></label><label><span>{isArabic ? 'ميزانية API الشهرية' : 'Monthly API budget'}</span><div className="money-input"><b>$</b><input type="number" min="0" value={budget} onChange={(event) => setBudget(event.target.value)} /></div><small>{isArabic ? 'تنبيه فقط—لا يتم الخصم من التطبيق.' : 'Used for alerts only; TEMM does not charge you.'}</small></label></div>
    </div>,
    <div className="onboarding-step intro" key="ready">
      <div className="onboarding-hero-mark ready"><Sparkles size={27} /></div>
      <span className="onboarding-kicker">READY</span>
      <h1>{isArabic ? 'اكتمل الإعداد الأساسي.' : 'Core setup is complete.'}</h1>
      <p>{isArabic ? 'كل مهمة ستمر بفحص جاهزية قبل التنفيذ. المسارات غير المتصلة ستتوقف وتوضح المطلوب بدل إنتاج نتيجة وهمية.' : 'Every task now passes a readiness check. Unconnected routes stop and explain what is missing instead of producing a synthetic result.'}</p>
      <div className="ready-summary"><div><span>{isArabic ? 'أدوات مكتشفة' : 'Discovered tools'}</span><strong>{tools.length}</strong></div><div><span>{isArabic ? 'مزودات متصلة' : 'Connected providers'}</span><strong>{configuredProviders}</strong></div><div><span>{isArabic ? 'مساحات عمل' : 'Workspaces'}</span><strong>{workspaceCount}</strong></div></div>
    </div>,
  ];

  return (
    <div className="onboarding-overlay" role="dialog" aria-modal="true">
      <div className="onboarding-shell">
        <aside className="onboarding-rail"><div className="brand-lockup"><div className="brand-mark"><Command size={19} /></div><div><div className="brand-name">TEMM</div><div className="brand-subtitle">{isArabic ? 'إعداد مساحة العمل' : 'Workspace setup'}</div></div></div><div className="onboarding-progress">{[0, 1, 2, 3, 4, 5].map((item) => <div key={item} className={step === item ? 'active' : step > item ? 'done' : ''}><span>{step > item ? <Check size={11} /> : item + 1}</span><div>{item === 0 ? (isArabic ? 'مرحبًا' : 'Welcome') : item === 1 ? (isArabic ? 'اكتشاف' : 'Discover') : item === 2 ? (isArabic ? 'اتصالات' : 'Connect') : item === 3 ? (isArabic ? 'مساحة عمل' : 'Workspace') : item === 4 ? (isArabic ? 'تفضيلات' : 'Defaults') : (isArabic ? 'جاهز' : 'Ready')}</div></div>)}</div><p>{isArabic ? 'يمكن إعادة تشغيل الإعداد من Settings في أي وقت.' : 'You can rerun setup from Settings at any time.'}</p></aside>
        <main className="onboarding-main"><div className="onboarding-content">{content[step]}</div><footer className="onboarding-footer"><button type="button" className="btn-secondary" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}><ArrowLeft size={14} /> {isArabic ? 'السابق' : 'Back'}</button><span>{step + 1} / 6</span>{step === 5 ? <button type="button" className="btn-primary" onClick={finish}>{isArabic ? 'افتح لوحة التحكم' : 'Open dashboard'} <Sparkles size={14} /></button> : <button type="button" className="btn-primary" onClick={() => setStep(Math.min(5, step + 1))}>{isArabic ? 'التالي' : 'Continue'} <ArrowRight size={14} /></button>}</footer></main>
      </div>
    </div>
  );
};
