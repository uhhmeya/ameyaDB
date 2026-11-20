import { useEffect, useRef, useState } from 'react'

const RELAY_URL = "ws://107.20.154.53:8765"
const INITIAL_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 5000

export const NUM_NODES = 5

export type NodeResult = {
    commit_idx: number
    term: number
}

export type TestResults = {
    nodes: (NodeResult | null)[]
    agree: boolean
}

export type ClusterUpdate = {
    event: string | null
    results: TestResults | null
    born_dead_or_participating: number
    compile_failed: boolean
    wall_us: number
}

export function useRelay() {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF_MS)
    const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)

    const [connected, setConnected] = useState(false)
    const [log, setLog] = useState<ClusterUpdate[]>([])

    useEffect(() => {
        connectToRelay()
        return () => disconnectFromRelay()
    }, [])

    function connectToRelay() {
        cancelledRef.current = false
        const ws = new WebSocket(RELAY_URL)
        wsRef.current = ws

        ws.onopen = () => {
            backoffRef.current = INITIAL_BACKOFF_MS
            setConnected(true)
        }

        ws.onmessage = (event) => {
            const update: ClusterUpdate = JSON.parse(event.data)
            setLog(prev => [...prev, update])
        }

        // relay isn't up yet or went away: retry with backoff
        ws.onclose = () => {
            if (wsRef.current !== ws) return // stale socket from strict mode's double mount
            setConnected(false)
            if (cancelledRef.current) return
            retryTimerRef.current = setTimeout(connectToRelay, backoffRef.current)
            backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS)
        }
    }

    function disconnectFromRelay() {
        cancelledRef.current = true
        if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
        wsRef.current?.close()
    }

    function sendMsg(data: unknown) {
        wsRef.current?.send(JSON.stringify(data))
    }

    return { connected, log, sendMsg }
}
