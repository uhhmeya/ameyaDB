import { useEffect, useRef } from 'react'

const RELAY_URL = "ws://localhost:8765"
const INITIAL_BACKOFF = 500
const MAX_BACKOFF = 5000

function Landing() {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)

    // tries to connect to relay on browser boot
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
        }

        // relay is not running
        ws.onclose = () => {
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

    return (
        <div className="fullscreen">
            <div className="instructions">
                <p className="command">
                    <span className="prompt">ameyaDB %</span>
                    <span> python3 relay.py</span>
                </p>
                <p className="hint">Run this to visualize</p>
            </div>
        </div>
    )
}

export default Landing