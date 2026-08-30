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
    msg: string
}

export function useRelay() {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)
    const [connected, setConnected] = useState(false)
    const [messages, setMessages] = useState<msg[]>([])
    const [hellos, setHellos] = useState(0)



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

        // relay sends msg
        ws.onmessage = (event) => {
            const data: msg = JSON.parse(event.data)
            handle_msg(data)
        }

        function handle_msg(data: msg) {
            if (data.msg === 'hello') {
                setHellos(prev => prev + 1)
                return
            }
            setMessages(prev => [...prev, data])
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

    return { connected, messages, hellos, send_msg }
}