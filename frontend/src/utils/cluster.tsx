import type { msg } from '../utils/useRelay.tsx'

export type Action = 'put' | 'lost'
export type Role = 'reader' | 'writer'

export type LinkEvent = {
    seq: number
    ts: string
    node: number
    incarnation: number
    action: Action
    role: Role
    a: number
    b: number
    peer: number
    raw: string
}

export type Endpoint = {
    writer: boolean
    reader: boolean
    ts: string
    seq: number
}

export type LinkState = {
    a: number
    b: number
    a_side: Endpoint | null
    b_side: Endpoint | null
    healthy: boolean
}

export type NodeState = {
    id: number
    degree: number
    peers: number[]
    last_ts: string | null
    last_seq: number
    incarnation: number
}

export type Cluster = {
    events: LinkEvent[]
    unparsed: string[]
    nodes: NodeState[]
    links: LinkState[]
}

const BODY = /^(?:\d+\s+)?(put|lost)\s+(reader|writer)\s+on\s+(\d+)<--->(\d+)$/

function format_ts(wall_us: number): string {
    return new Date(wall_us / 1000).toISOString().slice(11, 23)   // HH:MM:SS.mmm
}

export function parse_event(entry: msg): LinkEvent | null {
    const body = BODY.exec(entry.msg.trim())
    if (!body) return null

    const node = entry.node
    const a = Number(body[3])
    const b = Number(body[4])
    if (node !== a && node !== b) return null

    return {
        seq: entry.seq,
        ts: format_ts(entry.wall_us),
        node,
        incarnation: entry.life,
        action: body[1] as Action,
        role: body[2] as Role,
        a,
        b,
        peer: node === a ? b : a,
        raw: entry.msg,
    }
}

const up = (e: Endpoint | null) => e !== null && e.writer && e.reader

export function build_cluster(messages: msg[], num_nodes = 5): Cluster {
    const events: LinkEvent[] = []
    const unparsed: string[] = []
    const ends = new Map<string, Endpoint>()
    const last = new Map<number, LinkEvent>()

    messages.forEach((entry) => {
        const e = parse_event(entry)
        if (!e) {
            if (entry.msg.trim()) unparsed.push(entry.msg)
            return
        }
        events.push(e)

        const key = `${e.node}->${e.peer}`
        const cur = ends.get(key) ?? { writer: false, reader: false, ts: e.ts, seq: e.seq }
        cur[e.role] = e.action === 'put'
        cur.ts = e.ts
        cur.seq = e.seq
        ends.set(key, cur)

        last.set(e.node, e)
    })

    const links: LinkState[] = []
    for (let a = 0; a < num_nodes; a++) {
        for (let b = a + 1; b < num_nodes; b++) {
            const a_side = ends.get(`${a}->${b}`) ?? null
            const b_side = ends.get(`${b}->${a}`) ?? null
            links.push({ a, b, a_side, b_side, healthy: up(a_side) && up(b_side) })
        }
    }

    const nodes: NodeState[] = []
    for (let id = 0; id < num_nodes; id++) {
        const peers = links
            .filter(l => l.healthy && (l.a === id || l.b === id))
            .map(l => (l.a === id ? l.b : l.a))
        const seen = last.get(id)
        nodes.push({
            id,
            degree: peers.length,
            peers,
            last_ts: seen ? seen.ts : null,
            last_seq: seen ? seen.seq : -1,
            incarnation: seen ? seen.incarnation : 0,
        })
    }

    return { events, unparsed, nodes, links }
}