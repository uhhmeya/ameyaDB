import type { ClusterUpdate } from '../hooks/useRelay.tsx'

type DebugProps = {
    log: ClusterUpdate[]
}

function Debug({ log }: DebugProps) {
    const events = log.filter(update => update.event)
    const results = log.findLast(update => update.results)?.results

    return (
        <div className="fullscreen">
            <div className="events">
                {events.map((update, i) => (
                    <div key={i}>{update.event}</div>
                ))}
            </div>
            <div className="results">
                {results ? (
                    <>
                        <table>
                            <thead>
                                <tr>
                                    <th></th>
                                    <th>commit index</th>
                                    <th>term</th>
                                </tr>
                            </thead>
                            <tbody>
                                {results.nodes.map((node, i) => (
                                    <tr key={i}>
                                        <td>node{i}</td>
                                        {node ? (
                                            <>
                                                <td>{node.commit_idx}</td>
                                                <td>{node.term}</td>
                                            </>
                                        ) : (
                                            <td colSpan={2}>no reply</td>
                                        )}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        <p className="agreement">
                            agreement
                            <span className={results.agree ? 'checkbox agree' : 'checkbox disagree'}>
                                {results.agree ? '✓' : '✗'}
                            </span>
                        </p>
                    </>
                ) : 'running test...'}
            </div>
        </div>
    )
}

export default Debug
