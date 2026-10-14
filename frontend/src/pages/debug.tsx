import type { msg } from '../hooks/useRelay.tsx'
import { cluster_events } from '../utils/cluster'

interface DebugProps {
    log: msg[]
}

function Debug({ log }: DebugProps) {
    return (
        <div className="fullscreen">
            <ol>
                {cluster_events(log).map((e, i) => (
                    <li key={i}>{e.time} {e.text}</li>
                ))}
            </ol>
        </div>
    )
}

export default Debug