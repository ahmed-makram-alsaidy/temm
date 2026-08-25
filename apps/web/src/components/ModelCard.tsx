import React, { useState } from 'react';
import { Cpu } from 'lucide-react';
import type { Model } from '../services/api';
import { api } from '../services/api';

export const ModelCard: React.FC<{ model: Model; providerConfigured: boolean; onToggle: () => void; onBaseline: () => void; isArabic: boolean }> = ({ model, providerConfigured, onToggle, onBaseline, isArabic }) => {
  const [favoriteUseCase, setFavoriteUseCase] = useState('');
  const observed = model.availability_checked_at ? new Date(model.availability_checked_at).toLocaleString() : null;
  const state = !model.is_active || model.lifecycle_status === 'archived' ? 'disabled' : model.availability_state;
  return <article className="surface-card asset-card">
    <div className="asset-card-head"><div className="asset-icon"><Cpu size={17} /></div><span className={`status-badge model-${state}`}>{state}</span></div>
    <h3>{model.name}</h3><p>{model.description || `${model.provider} · ${model.category}`}</p>
    <div className="asset-tags"><span>{model.provider}</span><span>{model.registry_state}</span><span>{providerConfigured ? (isArabic ? 'المزود مهيأ' : 'Provider configured') : (isArabic ? 'المزود غير مهيأ' : 'Provider not configured')}</span></div>
    <div className="model-truth"><div><span>{isArabic ? 'المصدر' : 'Source'}</span><strong>{model.source_type} · {model.metadata_provenance}</strong></div><div><span>{isArabic ? 'التوافر' : 'Availability'}</span><strong>{model.availability_state}{observed ? ` · ${observed}` : ' · not observed'}</strong></div><div><span>{isArabic ? 'الأسعار' : 'Pricing'}</span><strong>{model.pricing_provenance}</strong></div><div><span>{isArabic ? 'القدرات' : 'Capabilities'}</span><strong>{model.capability_provenance}</strong></div></div>
    <div className="score-line"><span>{isArabic ? 'الجودة' : 'Quality'} <strong>{model.quality_score ?? (isArabic ? 'غير معروفة' : 'Unknown')}</strong></span><span>{isArabic ? 'السرعة' : 'Speed'} <strong>{model.speed_score ?? (isArabic ? 'غير معروفة' : 'Unknown')}</strong></span><span>{isArabic ? 'الاعتمادية' : 'Reliability'} <strong>{model.reliability_score ?? (isArabic ? 'غير معروفة' : 'Unknown')}</strong></span></div>
    <div className="model-favorite-control"><select aria-label={isArabic ? 'تفضيل حسب الاستخدام' : 'Favorite use case'} value={favoriteUseCase} onChange={async (event) => { const value = event.target.value; setFavoriteUseCase(value); if (value) await api.setModelFavorite(model.id, value); }}><option value="">{isArabic ? 'أضف كتفضيل…' : 'Add preference…'}</option><option value="coding">Coding</option><option value="research">Research</option><option value="arabic">Arabic</option><option value="images">Images</option></select><small>{isArabic ? 'تفضيل شخصي، وليس ترتيبًا مقاسًا' : 'Personal preference, not measured ranking'}</small></div>
    <div className="asset-actions"><button type="button" onClick={onToggle}>{model.is_active ? (isArabic ? 'إيقاف' : 'Pause') : (isArabic ? 'تفعيل' : 'Enable')}</button><button type="button" className={model.is_reference_baseline ? 'baseline' : ''} onClick={onBaseline}>{model.is_reference_baseline ? (isArabic ? 'الموديل المرجعي' : 'Baseline') : (isArabic ? 'اجعله مرجعيًا' : 'Set baseline')}</button></div>
  </article>;
};
