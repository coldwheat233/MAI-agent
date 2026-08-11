// ── Auto-Scroll Hook ────────────────────────────
import { useEffect, useRef, useCallback } from 'react'

export function useAutoScroll(dependency: unknown) {
  const containerRef = useRef<HTMLDivElement>(null)
  const userScrolledUp = useRef(false)

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    // If user is within 60px of bottom, consider them "at bottom"
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    userScrolledUp.current = distanceFromBottom > 60
  }, [])

  // Auto-scroll when dependency changes, unless user scrolled up
  useEffect(() => {
    const el = containerRef.current
    if (!el || userScrolledUp.current) return
    el.scrollTop = el.scrollHeight
  }, [dependency])

  // Reset userScrolledUp when dependency changes significantly (new message added)
  useEffect(() => {
    userScrolledUp.current = false
  }, [dependency])

  return { containerRef, handleScroll }
}
