import { useCallback, useState } from 'react'
import type { msg } from './useRelay.tsx'

export function useCluster() {
    const [hellos, setHellos] = useState(0)

    const ingest = useCallback((m: msg) => {
        if (m.type === 'hello') setHellos(prev => prev + 1)
    }, [])

    return { hellos, ingest }
}