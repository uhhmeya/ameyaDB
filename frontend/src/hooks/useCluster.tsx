import { useCallback, useState } from 'react'
import type { msg } from './useRelay.tsx'

export function useCluster() {
    const [hellos, setHellos] = useState(0)
    const [compile_failed, setCompileFailed] = useState(false)

    const ingest = useCallback((m: msg) => {
        if (m.type === 'hello') setHellos(prev => prev + 1)
        if (m.type === 'compile') setCompileFailed(true)
    }, [])

    return { hellos, compile_failed, ingest }
}