import { useI18n } from '../../../shared/lib/i18n';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../shared/ui/Dialog';

interface ConverterGuideDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ConverterGuideDialog({ open, onOpenChange }: ConverterGuideDialogProps) {
  const { t, locale } = useI18n();
  const libreOfficeUrl =
    locale === 'en'
      ? 'https://www.libreoffice.org/download/download/'
      : 'https://zh-cn.libreoffice.org/download/download/';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="converter-guide-dialog">
        <DialogHeader>
          <DialogTitle>{t('office.converter.guide.title')}</DialogTitle>
          <DialogDescription>{t('office.converter.guide.body')}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <a
            href={libreOfficeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t('office.converter.guide.download')}
          </a>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
