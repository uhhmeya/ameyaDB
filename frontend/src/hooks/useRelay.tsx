import { useEffect, useRef, useState, useCallback } from 'react'

const RELAY_URL = "ws://107.20.154.53:8765"
const INITIAL_BACKOFF = 500
const MAX_BACKOFF = 5000

export const NUM_NODES = 5

export type msg = {
    node: number
    life: number
    seq: number
    wall_us: number
    err_us: number
    type: string
    msg: string
}

export function useRelay(on_msg: (m: msg) => void) {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)
    const on_msg_ref = useRef(on_msg)
    on_msg_ref.current = on_msg

    const [connected, setConnected] = useState(false)
    const [log, setLog] = useState<msg[]>([])

    useEffect(() => {
        connect_to_relay()
        return () => disconnect_from_relay()
    }, [])

    function connect_to_relay() {
        cancelledRef.current = false
        const ws = new WebSocket(RELAY_URL)
        wsRef.current = ws

        // relay accepts connection
        ws.onopen = () => {
            backoffRef.current = INITIAL_BACKOFF
            setConnected(true)
        }

        //! handle msg from relay
        ws.onmessage = (event) => {
            const data: msg = JSON.parse(event.data)
            setLog(prev => [...prev, data]) // calls ingest
            on_msg_ref.current(data)
        }

        // can't connect to relay
        ws.onclose = () => {
            if (wsRef.current !== ws) return // strict mode
            setConnected(false)
            if (cancelledRef.current) return
            timeoutRef.current = setTimeout(connect_to_relay, backoffRef.current)
            backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF)
        }
    }

    function disconnect_from_relay() {
        cancelledRef.current = true
        if (timeoutRef.current) clearTimeout(timeoutRef.current)
        wsRef.current?.close()
    }

    // sends msg to relay
    const send_msg = useCallback((data: unknown) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(data))
        }
    }, [])

    return { connected, log, send_msg }
}