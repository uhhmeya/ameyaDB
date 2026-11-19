import type { ClusterUpdate } from '../hooks/useRelay.tsx'

type DebugProps = {
    log: ClusterUpdate[]
}

function Debug({ log }: DebugProps) {
    return (
        <div className="fullscreen">
            <div className="events">
                {log.map((update, i) => (
                    <div key={i}>{new Date(update.wall_us / 1000).toLocaleTimeString()} → {update.event}</div>
                ))}
            </div>
        </div>
    )
}

export default Debug
