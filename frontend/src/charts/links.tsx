import type { Frame } from '../hooks/useRelay.tsx'
import { NUM_NODES } from '../hooks/useRelay.tsx'
import { NODE_COLORS } from './scale.ts'

// who can talk to whom at one moment. row = sender, column = receiver, so a one way fault shows up lopsided

const LINK_STATES: Record<string, { name: string, mark: string }> = {
    '0': { name: 'fine', mark: '' },
    '1': { name: 'cut by the firewall', mark: '✕' },
    '2': { name: 'every msg dropped', mark: '∅' },
    '3': { name: 'losing msgs', mark: '%' },
    '4': { name: 'slow', mark: '~' },
}
const ROLE_MARKS = ['f', 'c', 'L', 'p']
const ROLE_NAMES = ['follower', 'candidate', 'leader', 'asking for pre-votes']

type LinksProps = {
    frame: Frame | null
}

function Links({ frame }: LinksProps) {
    if (!frame) return <p className="quiet">no data yet</p>

    const cells = []
    for (let sender = 0; sender < NUM_NODES; sender++) {
        cells.push(<div key={`from${sender}`} className="links-name">n{sender}</div>)

        for (let receiver = 0; receiver < NUM_NODES; receiver++) {
            const node = frame.nodes[sender]

            // the diagonal is the node itself
            if (sender === receiver) {
                const what = !node.up ? 'down' : node.up === 2 ? 'gone quiet' : ROLE_NAMES[node.role ?? 0]
                cells.push(
                    <div key={`${sender}${receiver}`} className={node.up ? 'links-node' : 'links-node down'}
                         style={node.up ? { background: NODE_COLORS[sender] } : undefined} title={`node${sender}: ${what}`}>
                        {!node.up ? '' : node.up === 2 ? 'z' : ROLE_MARKS[node.role ?? 0]}
                    </div>,
                )
                continue
            }

            const state = LINK_STATES[frame.links[sender * NUM_NODES + receiver]] ?? LINK_STATES['0']
            const wireUp = node.up > 0 && ((node.conn ?? 0) >> receiver) & 1
            cells.push(
                <div key={`${sender}${receiver}`} className={`links-cell link-${frame.links[sender * NUM_NODES + receiver]}`}
                     title={`node${sender} → node${receiver}: ${state.name}. tcp wire is ${wireUp ? 'up' : 'down'}`}>
                    {state.mark || (wireUp ? '·' : '')}
                </div>,
            )
        }
    }

    return (
        <div className="links">
            <div className="links-grid" role="img" aria-label="which node can send to which node">
                <div />
                {Array.from({ length: NUM_NODES }, (_, node) => <div key={node} className="links-name">n{node}</div>)}
                {cells}
            </div>
            <p className="links-key">
                row sends, column receives. <span className="link-1 key">✕</span> firewall cut <span className="link-2 key">∅</span> all msgs dropped{' '}
                <span className="link-3 key">%</span> lossy <span className="link-4 key">~</span> slow. a dot means the tcp wire is up
            </p>
        </div>
    )
}

export default Links
