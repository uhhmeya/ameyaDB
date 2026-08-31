import { useEffect, useRef } from 'react'
import type { Cluster, NodeState } from '../utils/cluster'
import type { msg } from '../hooks/useRelay.tsx'

interface DebugProps {
    cluster: Cluster
    log: msg[]
}

function Debug({ cluster, log }: DebugProps) {
    const log_ref = useRef<HTMLDivElement | null>(null)

    const total = cluster.nodes.length - 1
    const healthy = cluster.links.filter(l => l.isUP).length

    useEffect(() => {
        const el = log_ref.current
        if (el) el.scrollTop = el.scrollHeight
    }, [log.length])

    const card_class = (n: NodeState) => {
        if (n.last_ts === null) return 'node-card silent'
        if (n.peers.length === 0) return 'node-card down'
        if (n.peers.length < total) return 'node-card degraded'
        return 'node-card'
    }

    return (
        <div className="fullscreen debug-page">
            <div className="node-row">
                {cluster.nodes.map(n => (
                    <div key={n.id} className={card_class(n)}>
                        <div className="node-card-id">node {n.id}</div>
                        <div>degree {n.peers.length}/{total}</div>
                        <div>seen {n.last_ts ?? '--'}</div>
                    </div>
                ))}
            </div>

            <div className="cluster-summary">
                links {healthy}/{cluster.links.length} healthy
                {cluster.unparsed.length > 0 && (
                    <span className="alert"> · {cluster.unparsed.length} unparsed</span>
                )}
            </div>

            <div className="log" ref={log_ref}>
                {log.map((m, i) => <div key={i}>{m.msg}</div>)}
            </div>
        </div>
    )
}

export default Debug