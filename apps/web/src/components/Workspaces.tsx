import React, { useEffect, useState } from 'react';
import { Check, FolderKanban, FolderPlus, HardDrive, ShieldCheck, Star, TerminalSquare, Trash2 } from 'lucide-react';
import type { Workspace } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';

export const Workspaces: React.FC<{ onOpenConsole: () => void }> = ({ onOpenConsole }) => {
  const { isArabic } = useLanguage();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [profile, setProfile] = useState<'safe' | 'developer' | 'full'>('developer');
  const [shells, setShells] = useState<Array<'powershell' | 'cmd'>>(['powershell']);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [removeConfirm, setRemoveConfirm] = useState<string | null>(null);

  const load = () => api.listWorkspaces().then(setWorkspaces).catch(console.error);
  useEffect(() => { load(); }, []);

  const addWorkspace = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !path.trim()) return;
    setSaving(true); setError('');
    try {
      await api.createWorkspace({ name: name.trim(), path: path.trim(), permission_profile: profile, allowed_shells: shells, is_default: !workspaces.length });
      setName(''); setPath(''); setProfile('developer'); setShells(['powershell']); setShowForm(false); await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : (isArabic ? 'تعذر إضافة مساحة العمل.' : 'Could not add workspace.'));
    } finally { setSaving(false); }
  };

  const toggleShell = (shell: 'powershell' | 'cmd') => setShells((current) => current.includes(shell) ? current.filter((item) => item !== shell) : [...current, shell]);

  const remove = async (workspace: Workspace) => {
    if (removeConfirm !== workspace.id) { setRemoveConfirm(workspace.id); return; }
    await api.removeWorkspace(workspace.id); setRemoveConfirm(null); await load();
  };

  return (
    <div className="product-page workspaces-page">
      <div className="product-page-head">
        <div><div className="eyebrow"><ShieldCheck size={13} /> Local permission boundary</div><h1>{isArabic ? 'مساحات العمل' : 'Workspaces'}</h1><p>{isArabic ? 'حدد المجلدات التي يمكن للوكلاء والأوامر الوصول إليها. لا يوجد وصول تلقائي لباقي الجهاز.' : 'Approve the folders agents and commands may access. The rest of the computer stays outside their boundary.'}</p></div>
        <button type="button" className="btn-primary" onClick={() => setShowForm((value) => !value)}><FolderPlus size={15} /> {isArabic ? 'إضافة مساحة عمل' : 'Add workspace'}</button>
      </div>

      <section className="workspace-policy surface-card">
        <ShieldCheck size={18} />
        <div><strong>{isArabic ? 'قاعدة التنفيذ' : 'Execution policy'}</strong><span>{isArabic ? 'أي Agent يقرأ أو يعدّل ملفات يحتاج Workspace معتمدًا أولًا. إزالة Workspace من هنا لا تحذف أي ملفات من جهازك.' : 'Any agent that reads or edits files needs an approved workspace first. Removing a workspace here never deletes its files.'}</span></div>
      </section>

      {showForm && (
        <form className="surface-card workspace-form" onSubmit={addWorkspace}>
          <div className="panel-heading"><div><h2>{isArabic ? 'ربط مجلد مشروع' : 'Connect a project folder'}</h2><p>{isArabic ? 'المسار يجب أن يكون موجودًا بالفعل على الجهاز.' : 'The folder must already exist on this computer.'}</p></div></div>
          <div className="workspace-form-grid">
            <label><span>{isArabic ? 'اسم المشروع' : 'Workspace name'}</span><input className="input-text" value={name} onChange={(event) => setName(event.target.value)} placeholder={isArabic ? 'مثال: نظام العيادة' : 'e.g. Clinic CRM'} /></label>
            <label className="path-field"><span>{isArabic ? 'المسار الكامل' : 'Absolute folder path'}</span><input className="input-text font-mono" dir="ltr" value={path} onChange={(event) => setPath(event.target.value)} placeholder="D:\\projects\\my-app" /></label>
            <label><span>{isArabic ? 'ملف الصلاحيات' : 'Permission profile'}</span><select className="input-text" value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}><option value="safe">Safe · read only</option><option value="developer">Developer · workspace write</option><option value="full">Full · explicit commands</option></select></label>
          </div>
          <div className="shell-picker"><span>{isArabic ? 'الـShell المسموح' : 'Allowed shells'}</span><div>{(['powershell', 'cmd'] as const).map((shell) => <button type="button" key={shell} className={shells.includes(shell) ? 'active' : ''} onClick={() => toggleShell(shell)}>{shells.includes(shell) && <Check size={11} />}{shell}</button>)}</div></div>
          {error && <StateNotice state="error" title="Workspace operation failed" detail={error} />}
          <div className="workspace-form-actions"><button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{isArabic ? 'إلغاء' : 'Cancel'}</button><button type="submit" className="btn-primary" disabled={saving || !name.trim() || !path.trim() || !shells.length}>{saving ? (isArabic ? 'جارٍ التحقق…' : 'Verifying…') : (isArabic ? 'تحقق وأضف' : 'Verify and add')}</button></div>
        </form>
      )}

      {!workspaces.length ? (
        <section className="surface-card workspace-empty"><FolderKanban size={24} /><h2>{isArabic ? 'لا توجد مساحة عمل معتمدة' : 'No approved workspace yet'}</h2><p>{isArabic ? 'أضف مجلد مشروع قبل تشغيل Codex أو Claude أو أي أمر يمكنه قراءة الملفات.' : 'Add a project folder before running Codex, Claude, or any command that can read files.'}</p><button type="button" className="btn-primary" onClick={() => setShowForm(true)}>{isArabic ? 'إضافة أول مشروع' : 'Add first project'}</button></section>
      ) : (
        <div className="workspace-grid">
          {workspaces.map((workspace) => (
            <article className="surface-card workspace-card" key={workspace.id}>
              <div className="workspace-card-head"><span className="workspace-folder"><FolderKanban size={18} /></span>{workspace.is_default && <span className="status-badge completed"><Star size={11} /> {isArabic ? 'افتراضية' : 'Default'}</span>}</div>
              <h2>{workspace.name}</h2><code>{workspace.path}</code>
              <div className="workspace-meta"><div><ShieldCheck size={13} /><span>{isArabic ? 'الصلاحيات' : 'Permissions'}</span><strong>{workspace.permission_profile}</strong></div><div><TerminalSquare size={13} /><span>Shells</span><strong>{workspace.allowed_shells.join(', ')}</strong></div><div><HardDrive size={13} /><span>{isArabic ? 'آخر استخدام' : 'Last used'}</span><strong>{workspace.last_used_at ? new Date(workspace.last_used_at).toLocaleDateString() : (isArabic ? 'لم يستخدم' : 'Never')}</strong></div></div>
              <div className="workspace-actions">{!workspace.is_default && <button type="button" onClick={async () => { await api.updateWorkspace(workspace.id, { is_default: true }); load(); }}><Star size={13} /> {isArabic ? 'اجعلها افتراضية' : 'Make default'}</button>}<button type="button" onClick={onOpenConsole}><TerminalSquare size={13} /> {isArabic ? 'فتح Console' : 'Open console'}</button><button type="button" className={removeConfirm === workspace.id ? 'danger-confirm' : ''} onClick={() => remove(workspace)}><Trash2 size={13} /> {removeConfirm === workspace.id ? (isArabic ? 'تأكيد الإزالة' : 'Confirm remove') : (isArabic ? 'إزالة الربط' : 'Remove')}</button></div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

