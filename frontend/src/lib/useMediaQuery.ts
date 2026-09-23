import { useSyncExternalStore } from 'react'

/** Whether a media query matches, kept in step as the window changes. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** The width at which the navigation stops being a drawer and stays open beside the page. */
export const DESKTOP = '(min-width: 1024px)'
