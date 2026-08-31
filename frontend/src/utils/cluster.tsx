import type { msg } from '../hooks/useRelay'

export type WireState = {
    a: number
    b: number
    isUP: boolean
}

export type NodeState = {
    id: number
    peers: number[]
    last_ts: string | null
    life: number
}

export type Cluster = {
    nodes: NodeState[]
    links: WireState[]
    unparsed: string[] // junk
}

export type ClusterState = {
    n: number
    side: boolean[][]
    last_ts: (string | null)[]
    life: number[]
    unparsed: string[] //junk
}

const LINK = /^(\d+)\s+(\d+)\s+(up|down)$/

const stamp = (wall_us: number) =>
    new Date(wall_us / 1000).toISOString().slice(11, 23)   // HH:MM:SS.mmm

export function empty_state(n = 5): ClusterState {
    return {
        n,
        side: Array.from({ length: n }, () => Array<boolean>(n).fill(false)),
        last_ts: Array<string | null>(n).fill(null),
        life: Array<number>(n).fill(0),
        unparsed: [], // junk
    }
}

// updates side cells with T/F
function apply_wire(s: ClusterState, m: msg) {
    const g = LINK.exec(m.msg.trim())
    if (!g) { s.unparsed.push(m.msg); return }
    const sender = Number(g[1]), peer = Number(g[2])
    if (sender !== m.node || peer < 0 || peer >= s.n) { s.unparsed.push(m.msg); return }
    s.side[m.node][peer] = g[3] === 'up'
}

export function apply_msg(s: ClusterState, m: msg) {

    // new life means break old wires
    if (m.life > s.life[m.node]) {
        s.life[m.node] = m.life
        s.side[m.node].fill(false)
    }

    s.last_ts[m.node] = stamp(m.wall_us)

    // update wire connections
    if (m.type === 'wire')
        apply_wire(s, m)
}

export function derive(s: ClusterState): Cluster {
    const links: WireState[] = []
    for (let a = 0; a < s.n; a++)
        for (let b = a + 1; b < s.n; b++)
            links.push({ a, b, isUP: s.side[a][b] && s.side[b][a] })
    const nodes: NodeState[] = Array.from({ length: s.n }, (_, id) => ({
        id,
        peers: links
            .filter(l => l.isUP && (l.a === id || l.b === id))
            .map(l => (l.a === id ? l.b : l.a)),
        last_ts: s.last_ts[id],
        life: s.life[id],
    }))
    return { nodes, links, unparsed: s.unparsed }
}