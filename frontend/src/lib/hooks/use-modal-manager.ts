'use client'

import { useRouter, useSearchParams, usePathname } from 'next/navigation'

export type ModalType = 'source' | 'note' | 'insight'

export function useModalManager() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const pathname = usePathname()

  // Read current modal state from URL params
  const modalType = searchParams?.get('modal') as ModalType | null
  const modalId = searchParams?.get('id')
  // Decision #20: physical page from a `[source:id#p=N]` citation, so the source
  // modal can open the inline PDF at that page. Absent for non-page citations.
  const modalPageRaw = searchParams?.get('page')
  const modalPageParsed = modalPageRaw != null ? parseInt(modalPageRaw, 10) : NaN
  const modalPage = Number.isNaN(modalPageParsed) ? undefined : modalPageParsed

  /**
   * Open a modal by updating URL params without navigation
   * @param type - Type of modal to open (source, note, insight)
   * @param id - ID of the content to display
   * @param page - optional physical page for a page-level source citation
   */
  const openModal = (type: ModalType, id: string, page?: number) => {
    const params = new URLSearchParams(searchParams?.toString() || '')
    params.set('modal', type)
    params.set('id', id)
    if (page != null && Number.isFinite(page)) {
      params.set('page', String(page))
    } else {
      params.delete('page')
    }
    // Use scroll: false to prevent page from scrolling when modal state changes
    router.push(`${pathname}?${params.toString()}`, { scroll: false })
  }

  /**
   * Close the currently open modal by removing modal params from URL
   */
  const closeModal = () => {
    const params = new URLSearchParams(searchParams?.toString() || '')
    params.delete('modal')
    params.delete('id')
    params.delete('page')
    router.push(`${pathname}?${params.toString()}`, { scroll: false })
  }

  return {
    modalType,
    modalId,
    modalPage,
    openModal,
    closeModal,
    isOpen: !!modalType && !!modalId
  }
}
