import { useEffect, useRef, useState, useCallback } from 'react'

const RELAY_URL = "ws://107.20.160.98:8765"
const INITIAL_BACKOFF = 500
const MAX_BACKOFF = 5000

export function useRelay() {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)
    const [connected, setConnected] = useState(false)
    const [messages, setMessages] = useState<string[]>([])

    // tries to connect to relay on mount
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

        // a node logged something -- relay forwarded it here
        ws.onmessage = (event) => {
            setMessages(prev => [...prev, event.data])
        }

        // relay is not running / connection dropped
        ws.onclose = () => {
            // stale socket from a StrictMode remount -- ignore it
            if (wsRef.current !== ws) return

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

    // sends msg through WS
    const send_msg = useCallback((data: unknown) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(data))
        }
    }, [])

    return { connected, messages, send_msg }
}