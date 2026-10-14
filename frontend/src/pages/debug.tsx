import type { msg } from '../hooks/useRelay.tsx'
import { cluster_events } from '../utils/cluster'

interface DebugProps {
    log: msg[]
}

function Debug({ log }: DebugProps) {
    return (
        <div className="fullscreen">
            <div className="events">
                {cluster_events(log).map((e, i) => (
                    <div key={i}>{e.time} {e.text}</div>
                ))}
            </div>
        </div>
    )
}

export default Debug