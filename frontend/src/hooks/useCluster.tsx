import { useCallback, useState } from 'react'
import type { msg } from './useRelay.tsx'

export function useCluster() {
    const [born_dead_or_alive, setBornDeadOrAlive] = useState(0)
    const [compile_failed, setCompileFailed] = useState(false)

    const ingest = useCallback((m: msg) => {
        setBornDeadOrAlive(m.born_dead_or_alive)
        setCompileFailed(m.compile_failed)
    }, [])

    return { born_dead_or_alive, compile_failed, ingest }
}