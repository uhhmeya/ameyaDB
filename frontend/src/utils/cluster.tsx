import { NUM_NODES } from '../hooks/useRelay.tsx'
import type { msg } from '../hooks/useRelay.tsx'

const ALL_LINKS = NUM_NODES * (NUM_NODES - 1) / 2   // 5 nodes -> 10 links

// a link is up when both of its nodes say so: "2 3 up" and "3 2 up"
function count_links_up(says_up: boolean[][]) {
    let count = 0
    for (let a = 0; a < NUM_NODES; a++)
        for (let b = a + 1; b < NUM_NODES; b++)
            if (says_up[a][b] && says_up[b][a]) count++
    return count
}

// reads the relay log from the start and writes down each time the cluster changes
export function cluster_events(log: msg[]) {
    const events: { time: string, text: string }[] = []

    // says_up[a][b] = the last thing node a said about its wire to node b
    const says_up = Array.from({ length: NUM_NODES }, () => Array<boolean>(NUM_NODES).fill(false))
    let down_node: string | null = null

    for (const m of log) {
        if (m.type !== 'wire') continue

        const [a, b, state] = m.msg.split(' ')   // "1 3 down"
        const before = count_links_up(says_up)
        says_up[Number(a)][Number(b)] = state === 'up'
        const after = count_links_up(says_up)
        const time = new Date(m.wall_us / 1000).toLocaleTimeString()

        // the last missing link came up
        if (before < ALL_LINKS && after === ALL_LINKS) {
            events.push({ time, text: down_node === null ? 'cluster up' : `node${down_node} back up` })
            down_node = null
        }

        // the first link broke. node a sent this msg so it is alive, which means node b died
        if (before === ALL_LINKS && after < ALL_LINKS) {
            down_node = b
            events.push({ time, text: `node${b} down` })
        }

        // the last link broke
        if (before > 0 && after === 0) {
            events.push({ time, text: 'cluster down' })
            down_node = null
        }
    }

    return events
}