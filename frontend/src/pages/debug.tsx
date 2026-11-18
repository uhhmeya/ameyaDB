import type { msg } from '../hooks/useRelay.tsx'

interface DebugProps {
    log: msg[]
}

function Debug({ log }: DebugProps) {
    return (
        <div className="fullscreen">
            <div className="events">
                {log.filter(m => m.type === 'cluster').map((m, i) => (
                    <div key={i}>{new Date(m.wall_us / 1000).toLocaleTimeString()} {m.msg}</div>
                ))}
            </div>
        </div>
    )
}

export default Debug