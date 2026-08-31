import { useCallback, useRef, useState } from 'react'
import { NUM_NODES } from './useRelay.tsx'
import type { msg } from './useRelay.tsx'
import { apply_msg, derive, empty_state } from '../utils/cluster'
import type { Cluster } from '../utils/cluster'

export function useCluster(n = NUM_NODES) {
    const state = useRef(empty_state(n))
    const [cluster, setCluster] = useState<Cluster>(() => derive(state.current))
    const [hellos, setHellos] = useState(0)

    const ingest = useCallback((m: msg) => {
        if (m.type === 'hello') setHellos(prev => prev + 1)
        apply_msg(state.current, m)
        setCluster(derive(state.current))
    }, [])

    return { cluster, hellos, ingest }
}