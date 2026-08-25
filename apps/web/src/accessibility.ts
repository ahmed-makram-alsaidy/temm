import { useEffect, useRef } from 'react';

export const accessibilityChecklist = {
  automated: ['html-lang-dir', 'skip-link', 'main-landmark', 'focus-visible', 'reduced-motion', 'form-labels', 'button-names', 'heading-structure', 'duplicate-ids', 'dialog-focus'],
  manualRequired: ['contrast-all-themes', 'keyboard-all-workflows', 'screen-reader', 'rtl-visual-order'],
  fullComplianceClaimed: false,
} as const;

export const useDialogFocus = (onClose: () => void) => {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')].filter((item) => !item.hidden && item.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previous?.focus();
    };
  }, [onClose]);

  return { dialogRef, closeRef };
};
