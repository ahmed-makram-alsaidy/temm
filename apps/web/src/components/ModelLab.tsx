import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Brain, CheckCircle2, Code2, DollarSign, FlaskConical, Gauge, Languages, LockKeyhole, Play, Trophy, Zap } from 'lucide-react';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';

export const ModelLab: React.FC<{ onOpenConnections?: () => void }> = ({ onOpenConnections }) => {
  const { isArabic } = useLanguage();
  const [category, setCategory] = useState('all');
  const [leaderboard, setLeaderboard] = useState<any[]>([]);
  const [benchmarks, setBenchmarks] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [benchmarkResult, setBenchmarkResult] = useState<any>(null);
  const [benchmarkError, setBenchmarkError] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedWorkspace, setSelectedWorkspace] = useState('');
  const [tab, setTab] = useState<'overview' | 'run' | 'results'>('overview');

  const loadLeaderboard = useCallback(async () => {
    try { setLeaderboard(await api.getLeaderboard(category)); } catch (error) { console.error(error); }
  }, [category]);
  useEffect(() => { loadLeaderboard(); }, [loadLeaderboard]);
  useEffect(() => {
    Promise.all([api.listBenchmarks(), api.listAgents(), api.listWorkspaces()])
      .then(([b, a, w]) => { setBenchmarks(b); setAgents(a); setWorkspaces(w); })
      .catch(console.error);
  }, []);

  const readyAgents = useMemo(() => agents.filter((a: any) => a.tool_kind === 'agent' && a.user_enabled && a.discovery_state === 'verified' && a.status === 'ready' && a.auth_state !== 'failed'), [agents]);
  const fastest = useMemo(() => [...leaderboard].sort((a, b) => b.tokens_per_sec - a.tokens_per_sec)[0], [leaderboard]);
  const bestValue = useMemo(() => [...leaderboard].sort((a, b) => b.value_score - a.value_score)[0], [leaderboard]);
  const selected = leaderboard.filter((item) => selectedModels.includes(item.model_id));

  const canRunBenchmark = readyAgents.length > 0 && workspaces.length > 0;

  const runBenchmark = async () => {
    if (!selectedAgent || !selectedWorkspace || benchmarks.length === 0) return;
    setBenchmarkRunning(true);
    setBenchmarkError('');
    setBenchmarkResult(null);
    try {
      // Use the first benchmark suite available
      const result = await api.runRealBenchmark(benchmarks[0]?.id || '', selectedAgent, selectedWorkspace);
      if (result?.detail) {
        setBenchmarkError(typeof result.detail === 'string' ? result.detail : result.detail.message || 'Benchmark execution failed.');
      } else {
        setBenchmarkResult(result);
        loadLeaderboard();
      }
    } catch (error) {
      setBenchmarkError(error instanceof Error ? error.message : 'Benchmark failed.');
    } finally {
      setBenchmarkRunning(false);
    }
  };

  const tabs = [
    ['all', isArabic ? 'عام' : 'Overall', Trophy], ['coding', isArabic ? 'برمجة' : 'Coding', Code2], ['reasoning', isArabic ? 'استدلال' : 'Reasoning', Brain],
    ['arabic', isArabic ? 'عربي' : 'Arabic', Languages], ['speed', isArabic ? 'السرعة' : 'Speed', Zap], ['value', isArabic ? 'القيمة' : 'Value', DollarSign],
  ] as const;

  return (
    <div className="product-page model-lab-page">
      <div className="product-page-head">
        <div>
          <div className="eyebrow"><FlaskConical size={13} /> {isArabic ? 'ذكاء الاختيار' : 'Decision intelligence'}</div>
          <h1>{isArabic ? 'المقارنة والاختبار' : 'Benchmarks'}</h1>
          <p>{isArabic ? 'اختبر أدواتك الحقيقية، قارن النتائج المقاسة، واختر الأفضل لعملك.' : 'Test your actual tools, compare measured results, and choose what works best for your tasks.'}</p>
        </div>
        <div className="product-page-actions">
          <button type="button" className={`btn-secondary ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}>{isArabic ? 'نظرة عامة' : 'Overview'}</button>
          <button type="button" className={`btn-secondary ${tab === 'run' ? 'active' : ''}`} onClick={() => setTab('run')}>{isArabic ? 'تشغيل اختبار' : 'Run benchmark'}</button>
          <button type="button" className={`btn-secondary ${tab === 'results' ? 'active' : ''}`} onClick={() => setTab('results')}>{isArabic ? 'النتائج' : 'Results'}</button>
        </div>
      </div>

      {tab === 'overview' && <>
        {!canRunBenchmark && <section className="surface-card evidence-banner">
          <LockKeyhole size={18} />
          <div>
            <strong>{isArabic ? 'لا توجد نتائج مقاسة بعد' : 'No measured results yet'}</strong>
            <span>{isArabic ? 'ربط أداة CLI جاهزة ومساحة عمل معتمدة يمكّنك من تشغيل اختبارات حقيقية وقياس الأداء الفعلي.' : 'Connect a ready CLI tool and an approved workspace to run real tests and measure actual performance.'}</span>
          </div>
          <button type="button" className="btn-primary" onClick={onOpenConnections}>{isArabic ? 'ربط أداة' : 'Connect tool'}</button>
        </section>}

        {canRunBenchmark && !leaderboard.length && <section className="surface-card evidence-banner">
          <FlaskConical size={18} />
          <div>
            <strong>{isArabic ? 'أدواتك جاهزة للاختبار' : 'Your tools are ready to test'}</strong>
            <span>{isArabic ? 'لديك أداة جاهزة ومساحة عمل. شغّل أول اختبار لقياس الأداء الحقيقي بدلًا من التقديرات.' : 'You have a ready tool and workspace. Run your first benchmark to measure real performance instead of estimates.'}</span>
          </div>
          <button type="button" className="btn-primary" onClick={() => setTab('run')}><Play size={14} /> {isArabic ? 'شغّل اختبار' : 'Run benchmark'}</button>
        </section>}

        <div className="lab-summary">
          <article className="surface-card"><Trophy size={16} /><span>{isArabic ? 'الأفضل حتى الآن' : 'Top performer'}</span><strong>{leaderboard[0]?.name || '—'}</strong><small>{leaderboard[0] ? `${leaderboard[0].score}/100 · ${leaderboard[0].score_provenance || 'catalog'}` : (isArabic ? 'شغّل اختبارًا لقياس الأداء' : 'Run a benchmark to measure')}</small></article>
          <article className="surface-card"><Zap size={16} /><span>{isArabic ? 'الأسرع' : 'Fastest'}</span><strong>{fastest?.name || '—'}</strong><small>{fastest ? `${fastest.tokens_per_sec} tok/s` : '—'}</small></article>
          <article className="surface-card"><DollarSign size={16} /><span>{isArabic ? 'أفضل قيمة' : 'Best value'}</span><strong>{bestValue?.name || '—'}</strong><small>{bestValue ? `${bestValue.value_score}/100` : '—'}</small></article>
          <article className="surface-card"><FlaskConical size={16} /><span>{isArabic ? 'حزم اختبار' : 'Test packs'}</span><strong>{benchmarks.length}</strong><small>{readyAgents.length} {isArabic ? 'أداة جاهزة' : 'ready tools'}</small></article>
        </div>

        <div className="tab-strip lab-tabs">{tabs.map(([id, label, Icon]) => <button type="button" key={id} className={category === id ? 'active' : ''} onClick={() => setCategory(id)}><Icon size={13} /> {label}</button>)}</div>

        <div className="lab-layout">
          <section className="surface-card registry-leaderboard">
            <div className="panel-heading"><div><h2>{isArabic ? 'الترتيب' : 'Ranking'}</h2><p>{leaderboard.length ? (isArabic ? 'مرتّب حسب الأداء المقاس' : 'Ranked by measured performance') : (isArabic ? 'لا توجد نتائج مقاسة بعد' : 'No measured results yet')}</p></div>{leaderboard.length > 0 && <span className="status-badge">{leaderboard[0]?.score_provenance === 'measured' ? 'Measured' : 'Catalog'}</span>}</div>
            {leaderboard.length > 0 ? <>
              <div className="leaderboard-head"><span>#</span><span>{isArabic ? 'الأداة' : 'Tool'}</span><span>{isArabic ? 'الجودة' : 'Quality'}</span><span>{isArabic ? 'السرعة' : 'Speed'}</span><span>{isArabic ? 'القيمة' : 'Value'}</span></div>
              {leaderboard.map((item) => <button type="button" className={selectedModels.includes(item.model_id) ? 'selected' : ''} key={item.model_id} onClick={() => setSelectedModels((current) => current.includes(item.model_id) ? current.filter((id) => id !== item.model_id) : [...current, item.model_id].slice(-4))}><strong>{item.rank}</strong><div><b>{item.name}</b><small>{item.provider} · {item.is_local ? 'local' : 'cloud'}</small></div><span>{item.score ?? '—'}</span><span>{item.tokens_per_sec ? `${item.tokens_per_sec} t/s` : '—'}</span><span>{item.value_score ?? '—'}</span></button>)}
            </> : <div className="lab-empty-ranking"><FlaskConical size={28} /><p>{isArabic ? 'شغّل اختبارًا لرؤية النتائج هنا.' : 'Run a benchmark to see ranked results here.'}</p><button type="button" className="btn-primary" onClick={() => setTab('run')} disabled={!canRunBenchmark}><Play size={14} /> {isArabic ? 'تشغيل اختبار' : 'Run benchmark'}</button></div>}
          </section>

          <aside className="surface-card compare-tray">
            <div className="panel-heading"><div><h2>{isArabic ? 'مقارنة' : 'Compare'}</h2><p>{isArabic ? 'اختر حتى 4 من الترتيب' : 'Select up to 4 from ranking'}</p></div><BarChart3 size={17} /></div>
            {!selected.length ? <div className="mini-empty"><Activity size={20} /><span>{isArabic ? 'لم تختر أدوات' : 'No tools selected'}</span></div> : <div className="compare-models">{selected.map((item) => <article key={item.model_id}><strong>{item.name}</strong><small>{item.provider}</small><div><span><Code2 size={11} /> {isArabic ? 'برمجة' : 'Code'} <b>{item.coding_score ?? '—'}</b></span><span><Brain size={11} /> {isArabic ? 'استدلال' : 'Reason'} <b>{item.reasoning_score ?? '—'}</b></span><span><Languages size={11} /> {isArabic ? 'عربي' : 'Arabic'} <b>{item.arabic_score ?? '—'}</b></span><span><Gauge size={11} /> {isArabic ? 'موثوقية' : 'Reliable'} <b>{item.reliability_score ?? '—'}</b></span></div></article>)}</div>}
          </aside>
        </div>
      </>}

      {tab === 'run' && <section className="surface-card benchmark-run-panel">
        <h2>{isArabic ? 'تشغيل اختبار أداء' : 'Run a performance benchmark'}</h2>
        <p>{isArabic ? 'اختبر أداة حقيقية على مجموعة مهام محددة. النتائج تكون مقاسة وليست تقديرية.' : 'Test a real tool against a defined task set. Results are measured, not estimated.'}</p>

        <div className="benchmark-run-form">
          <label>
            <span>{isArabic ? 'الأداة' : 'Tool to test'}</span>
            <select value={selectedAgent} onChange={(e) => setSelectedAgent(e.target.value)} aria-label="Select agent">
              <option value="">{isArabic ? 'اختر أداة…' : 'Select a tool…'}</option>
              {readyAgents.map((a: any) => <option key={a.id} value={a.id}>{a.name} — {a.capabilities?.join(', ')}</option>)}
            </select>
          </label>
          <label>
            <span>{isArabic ? 'مساحة العمل' : 'Workspace'}</span>
            <select value={selectedWorkspace} onChange={(e) => setSelectedWorkspace(e.target.value)} aria-label="Select workspace">
              <option value="">{isArabic ? 'اختر مساحة عمل…' : 'Select workspace…'}</option>
              {workspaces.map((w: any) => <option key={w.id} value={w.id}>{w.name} — {w.path}</option>)}
            </select>
          </label>
          <label>
            <span>{isArabic ? 'حزمة الاختبار' : 'Test pack'}</span>
            <select disabled aria-label="Select benchmark pack">
              {benchmarks.length ? benchmarks.map((b: any) => <option key={b.id} value={b.id}>{b.name} — {b.category}</option>) : <option>{isArabic ? 'لا توجد حزم متاحة' : 'No packs available'}</option>}
            </select>
          </label>
        </div>

        {!canRunBenchmark && <StateNotice state="unknown" title={isArabic ? 'غير جاهز' : 'Not ready'} detail={isArabic ? 'تحتاج أداة CLI جاهزة ومساحة عمل معتمدة.' : 'You need a ready CLI tool and an approved workspace.'} />}
        {benchmarkError && <StateNotice state="error" title={isArabic ? 'فشل الاختبار' : 'Benchmark failed'} detail={benchmarkError} />}

        <div className="benchmark-run-actions">
          <button type="button" className="btn-primary" onClick={runBenchmark} disabled={!selectedAgent || !selectedWorkspace || benchmarkRunning || !benchmarks.length}>
            <Play size={14} /> {benchmarkRunning ? (isArabic ? 'جارٍ التنفيذ…' : 'Running…') : (isArabic ? 'بدء الاختبار' : 'Start benchmark')}
          </button>
          <small>{isArabic ? 'النتائج مقاسة حقيقيًا. لا يتم توليد درجات عشوائية.' : 'Results are genuinely measured. No random scores are generated.'}</small>
        </div>

        {benchmarkResult && <section className="benchmark-result surface-card">
          <h3><CheckCircle2 size={16} /> {isArabic ? 'نتائج مقاسة' : 'Measured results'}</h3>
          <div className="benchmark-result-grid">
            {benchmarkResult.cases?.map((c: any, i: number) => <div key={i} className="benchmark-case-result">
              <strong>{c.case_key || `Case ${i + 1}`}</strong>
              <span className={`status-badge ${c.score >= 80 ? 'badge-emerald' : c.score >= 50 ? 'badge-amber' : 'badge-muted'}`}>{c.score != null ? `${c.score}/100` : '—'}</span>
              <small>{c.score_provenance || 'measured'} · {c.duration_ms ? `${c.duration_ms}ms` : '—'}</small>
            </div>)}
          </div>
          <small className="provenance-note">{isArabic ? 'كل الدرجات مقاسة من تنفيذ حقيقي وليست تقديرية.' : 'All scores are measured from real execution, not estimated.'}</small>
        </section>}
      </section>}

      {tab === 'results' && <section className="surface-card">
        <h2>{isArabic ? 'سجل النتائج' : 'Results history'}</h2>
        <p>{isArabic ? 'كل اختبار سابق مع أدلة التنفيذ.' : 'Every past benchmark with execution evidence.'}</p>
        {leaderboard.length > 0 ? <div className="leaderboard-head"><span>#</span><span>{isArabic ? 'الأداة' : 'Tool'}</span><span>{isArabic ? 'الدرجة' : 'Score'}</span><span>{isArabic ? 'المصدر' : 'Source'}</span></div> : null}
        {leaderboard.map((item, i) => <div key={item.model_id} className="result-row"><strong>{i + 1}</strong><span>{item.name}</span><span>{item.score ?? '—'}/100</span><span className="status-badge">{item.score_provenance || 'catalog'}</span></div>)}
        {!leaderboard.length && <StateNotice state="empty" title={isArabic ? 'لا توجد نتائج' : 'No results yet'} detail={isArabic ? 'شغّل اختبارًا من تبويب "تشغيل اختبار" لبدء جمع الأدلة.' : 'Run a benchmark from the "Run benchmark" tab to start collecting evidence.'} />}
      </section>}
    </div>
  );
};
