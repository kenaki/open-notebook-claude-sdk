import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'

export function useErrorToast() {
  const { toast } = useToast()
  const { t } = useTranslation()

  return (error: unknown, fallbackKey?: string) => {
    toast({
      title: t('common.error'),
      description: getApiErrorMessage(error, t, fallbackKey),
      variant: 'destructive',
    })
  }
}
