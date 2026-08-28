import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { NUM_NODES } from '../utils/useRelay.tsx'

const COOLDOWN_MS = 10_000

interface RunProps {
    connected: boolean
    send_msg: (data: unknown) => void
    messages: string[]
    roster: number[]
}

function Run({ connected, send_msg, roster }: RunProps) {
    const navigate = useNavigate()
    const [remaining, setRemaining] = useState(0)
    const next_allowed = useRef(0)
    const timer = useRef<number | null>(null)

    // go to landing if relay crashes
    useEffect(() => {
        if (!connected) navigate('/')
    }, [connected])

    // cleanup
    useEffect(() => () => {
        if (timer.current !== null) clearInterval(timer.current)
    }, [])

    // wait 10s before going to /debug
    const wait = (ms: number, onDone: () => void) => {
        next_allowed.current = Date.now() + ms
        setRemaining(ms)

        timer.current = window.setInterval(() => {
            const left = next_allowed.current - Date.now()
            if (left <= 0) {
                clearInterval(timer.current!)
                timer.current = null
                setRemaining(0)
                onDone()
            } else {
                setRemaining(left)
            }
        }, 100)
    }

    const run = () => {
        const now = Date.now()
        if (now < next_allowed.current) return
        next_allowed.current = now + COOLDOWN_MS
        send_msg({ msg: 'run_test.py' })
        wait(COOLDOWN_MS, () => navigate('/debug'))
    }

    // the run button only exists when every node has said hello to the relay,
    // i.e. all 5 are born dead and waiting
    const ready = roster.length === NUM_NODES

    const locked = remaining > 0
    return (
        <div className="fullscreen">
            {ready ? (
                <button className="run-button" onClick={run} disabled={locked}>
                    {locked ? `wait ${Math.ceil(remaining / 1000)}s` : 'run test.py'}
                </button>
            ) : (
                <p className="hint">not all nodes are being born dead ({roster.length}/{NUM_NODES})</p>
            )}
        </div>
    )
}

export default Run