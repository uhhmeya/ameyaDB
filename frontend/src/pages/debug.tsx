import { useEffect, useRef } from 'react'
import { build_cluster } from '../utils/cluster'
import type { NodeState } from '../utils/cluster'

type DebugProps = {
    messages: string[]
}

function Debug({ messages = [] }: DebugProps) {
    const log_ref = useRef<HTMLDivElement | null>(null)

    const cluster = build_cluster(messages)
    const total = cluster.nodes.length - 1
    const healthy = cluster.links.filter(l => l.healthy).length

    useEffect(() => {
        const el = log_ref.current
        if (el) el.scrollTop = el.scrollHeight
    }, [messages.length])

    const card_class = (n: NodeState) => {
        if (n.last_ts === null) return 'node-card silent'
        if (n.degree === 0) return 'node-card down'
        if (n.degree < total) return 'node-card degraded'
        return 'node-card'
    }

    return (
        <div className="fullscreen debug-page">
            <div className="node-row">
                {cluster.nodes.map(n => (
                    <div key={n.id} className={card_class(n)}>
                        <div className="node-card-id">node {n.id}</div>
                        <div>degree {n.degree}/{total}</div>
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
                {messages.map((m, i) => <div key={i}>{m}</div>)}
            </div>
        </div>
    )
}

export default Debug