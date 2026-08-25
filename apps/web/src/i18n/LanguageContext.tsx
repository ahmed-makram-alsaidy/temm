import React, { createContext, useContext, useState, useEffect } from 'react';
import { translations } from './translations';
import type { Language } from './translations';

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: typeof translations['en'];
  dir: 'rtl' | 'ltr';
  isArabic: boolean;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>(() => {
    const saved = localStorage.getItem('ai_fleet_lang');
    return (saved === 'ar' || saved === 'en') ? saved : 'ar';
  });

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    localStorage.setItem('ai_fleet_lang', lang);
  };

  const isArabic = language === 'ar';
  const dir: 'rtl' | 'ltr' = isArabic ? 'rtl' : 'ltr';

  useEffect(() => {
    document.documentElement.setAttribute('dir', dir);
    document.documentElement.setAttribute('lang', language);
  }, [language, dir]);

  const value: LanguageContextType = {
    language,
    setLanguage,
    t: translations[language],
    dir,
    isArabic,
  };

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

// The provider and its hook intentionally live together as one context module.
// oxlint-disable-next-line react/only-export-components
export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};
