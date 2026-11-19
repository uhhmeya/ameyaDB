import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { NUM_NODES } from '../hooks/useRelay.tsx'

const COUNTDOWN_SECONDS = 10

type RunProps = {
    connected: boolean
    sendMsg: (data: unknown) => void
    bornDeadOrParticipating: number
    compileFailed: boolean
}

function Run({ connected, sendMsg, bornDeadOrParticipating, compileFailed }: RunProps) {
    const navigate = useNavigate()
    const [secondsLeft, setSecondsLeft] = useState(0)
    const ready = bornDeadOrParticipating >= NUM_NODES

    useEffect(() => {
        if (!connected) navigate('/')
    }, [connected])

    // after the test starts, count down once a second, then show the debug page
    useEffect(() => {
        if (secondsLeft === 0) return
        const timer = setTimeout(() => {
            setSecondsLeft(secondsLeft - 1)
            if (secondsLeft === 1) navigate('/debug')
        }, 1000)
        return () => clearTimeout(timer)
    }, [secondsLeft])

    function runTest() {
        sendMsg({ to: "relay", msg: "run_test.py" })
        setSecondsLeft(COUNTDOWN_SECONDS)
    }

    let content
    if (ready) {
        content = (
            <button className="run-button" onClick={runTest} disabled={secondsLeft > 0}>
                {secondsLeft > 0 ? `wait ${secondsLeft}s` : 'run test.py'}
            </button>
        )
    } else if (compileFailed) {
        content = <p className="hint">nodes failed to compile</p>
    } else {
        content = <p className="hint">waiting for all nodes to be born dead ({bornDeadOrParticipating}/{NUM_NODES})</p>
    }

    return <div className="fullscreen">{content}</div>
}

export default Run
