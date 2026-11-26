import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ClusterStatus, Recording, Sweep } from '../hooks/useRelay.tsx'
import { NUM_NODES } from '../hooks/useRelay.tsx'
import Header from '../header.tsx'
import Tracks from '../charts/tracks.tsx'
import Links from '../charts/links.tsx'
import Detect from '../charts/detect.tsx'
import Outages from '../charts/outages.tsx'
import { NODE_COLORS, fmtMs, fmtNum, fmtPct, fmtTime, nearestFrame } from '../charts/scale.ts'

const ROLE_NAMES = ['follower', 'candidate', 'leader', 'asking for pre-votes']

const VERDICTS: Record<string, { mark: string, tone: string, says: string }> = {
    AGREE: { mark: '✓', tone: 'good', says: 'all five nodes hold the same data' },
    LAGGING: { mark: '…', tone: 'warning', says: 'nothing conflicts, but some node never caught up' },
    DIVERGED: { mark: '✕', tone: 'critical', says: 'nodes hold different data at the same index' },
    INCONCLUSIVE: { mark: '?', tone: 'serious', says: 'a node never answered' },
}

type DebugProps = {
    recording: Recording
    events: string[]
    status: ClusterStatus
    sweep: Sweep | null
    sendMsg: (data: unknown) => void
}

function Debug({ recording, events, status, sweep, sendMsg }: DebugProps) {
    const [cursor, setCursor] = useState<number | null>(null)
    const { header, frames, faults, summary } = recording

    const latest = frames.length ? frames[frames.length - 1] : null
    const shown = cursor !== null && frames.length ? frames[nearestFrame(frames, cursor)] : latest
    const verdict = summary ? VERDICTS[summary.verdict] : null
    const metrics = summary?.metrics
    const when = cursor !== null && shown ? `at ${fmtTime(shown.t)}` : 'now'

    function downloadRun() {
        const blob = new Blob([JSON.stringify({ run: header, frames, summary })], { type: 'application/json' })
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob)
        link.download = `${header?.id ?? 'run'}.json`
        link.click()
        URL.revokeObjectURL(link.href)
    }

    const mostCaughtUp = shown ? Math.max(0, ...shown.nodes.filter(node => node.up).map(node => node.commit ?? 0)) : 0
    const flags = header ? Object.keys(header.flags).sort().map(flag => header.flags[flag] === 1 ? flag : `${flag}=${header.flags[flag]}`) : []
    const flagChips = header && header.label !== (flags.join('+') || 'baseline') ? (flags.length ? flags : ['no flags set']) : []
    const title = !header ? 'nothing has run yet' : header.mode === 'chaos' ? 'random chaos' : header.x !== null ? `${header.name}: ${header.x}` : header.name

    return (
        <div className="screen">
            <Header>
                {status.busy && <button className="ghost-button" onClick={() => sendMsg({ to: "relay", msg: "stop" })}>stop the test</button>}
                {frames.length > 0 && <button className="ghost-button" onClick={downloadRun}>download this run</button>}
            </Header>

            <main className="board">
                <div className="title-block">
                    <h1>{title}</h1>
                    {header && (
                        <div className="chips">
                            <span className="chip">{header.label}</span>
                            {flagChips.map(flag => <span key={flag} className="chip">{flag}</span>)}
                        </div>
                    )}
                    {summary
                        ? <span className={`status-chip ${summary.passed ? 'good' : 'critical'}`}>{summary.passed ? '✓ passed' : `✕ ${summary.verdict === 'AGREE' ? 'a check failed' : summary.verdict.toLowerCase()}`}</span>
                        : latest && <span className="status-chip">{latest.phase} {fmtTime(latest.t)}</span>}
                </div>

                {!header && (
                    <p className="empty">
                        Start a test from the <Link to="/run">run page</Link>, or open a run you downloaded earlier from the <Link to="/">first page</Link>.
                    </p>
                )}

                {header && sweep && header.sweep === sweep.id && (
                    <p className="note">
                        Run {Math.min(sweep.points.length + (summary ? 0 : 1), sweep.xs.length)} of {sweep.xs.length} in the {sweep.name} sweep.{' '}
                        <Link to="/compare">See the sweep so far</Link>
                    </p>
                )}

                {summary && verdict && metrics && (
                    <>
                        <section className="panel verdict">
                            <span className={`verdict-mark ${verdict.tone}`} aria-hidden="true">{verdict.mark}</span>
                            <div>
                                <h2>{verdict.says}</h2>
                                <p>
                                    <span className="chip">{summary.verdict.toLowerCase()}</span>
                                    <span>{summary.passed ? 'Every check passed.' : 'A check failed, so the database was cleared for the next run.'}</span>
                                    {summary.unsafe && <span>What the nodes held was kept on their disks under output/archive for debugging.</span>}
                                </p>
                            </div>
                        </section>

                        <div className="tiles">
                            <div className="tile"><span>writes got through</span><b>{fmtPct(metrics.availability)}</b><small>of {fmtNum(metrics.seconds)}s measured</small></div>
                            <div className="tile"><span>out of service</span><b>{fmtNum(metrics.oos, 1)}s</b><small>{fmtNum(metrics.oos_avoidable, 1)}s of it while some node could have led</small></div>
                            <div className="tile"><span>elections started</span><b>{fmtNum(metrics.elections)}</b><small>{fmtNum(metrics.leader_changes)} won, {fmtNum(metrics.term_growth)} terms burned{metrics.prevotes ? `, ${fmtNum(metrics.prevotes)} pre-vote rounds` : ''}</small></div>
                            {metrics.leader_faults
                                ? <div className="tile"><span>lost leader replaced in</span><b>{fmtMs(metrics.elect_ms)}</b><small>noticed in {fmtMs(metrics.detect_ms)}, writes back in {fmtMs(metrics.ots_ms)}</small></div>
                                : <div className="tile"><span>lost leader replaced in</span><b>–</b><small>no fault took the leader out</small></div>}
                            <div className="tile"><span>writes per second</span><b>{fmtNum(metrics.writes_per_sec)}</b><small>{fmtPct(metrics.goodput)} of the rate before the faults, p99 {fmtMs(metrics.p99)}</small></div>
                            <div className="tile"><span>back after the heal in</span><b>{metrics.recover_sec === null ? 'never' : fmtNum(metrics.recover_sec, 2) + 's'}</b><small>{fmtNum(metrics.snaps)} snapshots shipped</small></div>
                        </div>
                    </>
                )}

                {header && (
                    <div className="columns">
                        <section className="panel">
                            <h2>timeline</h2>
                            <p className="legend">
                                {Array.from({ length: NUM_NODES }, (_, node) => (
                                    <span key={node}><span className="line-key" style={{ background: NODE_COLORS[node] }} /> node {node}</span>
                                ))}
                                <span className="legend-gap" />
                                <span><span className="role-key thick" /> leading</span>
                                <span><span className="role-key medium" /> campaigning</span>
                                <span><span className="role-key hollow" /> asking for pre-votes</span>
                                <span><span className="role-key thin" /> following</span>
                                <span className="legend-gap" />
                                <span><span className="swatch outage" /> down, though a leader was possible</span>
                                <span><span className="swatch outage unavoidable" /> down, nobody could lead</span>
                            </p>
                            <Tracks recording={recording} cursor={cursor} setCursor={setCursor} />
                        </section>

                        <aside className="stack">
                            <section className="panel">
                                <h2>links <small>{when}</small></h2>
                                <Links frame={shown} />
                            </section>

                            <section className="panel">
                                <h2>nodes <small>{when}</small></h2>
                                <table className="grid-table">
                                    <thead><tr><th></th><th>doing</th><th>term</th><th>committed</th><th>behind</th></tr></thead>
                                    <tbody>
                                        {(shown?.nodes ?? []).map((node, i) => (
                                            <tr key={i}>
                                                <td><span className="line-key" style={{ background: NODE_COLORS[i] }} />node {i}</td>
                                                {node.up ? (
                                                    <>
                                                        <td>{node.up === 2 ? 'gone quiet' : ROLE_NAMES[node.role ?? 0]}</td>
                                                        <td>{fmtNum(node.term)}</td>
                                                        <td>{fmtNum(node.commit)}</td>
                                                        <td>{fmtNum(mostCaughtUp - (node.commit ?? 0))}</td>
                                                    </>
                                                ) : (
                                                    <td colSpan={4} className="quiet">down</td>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </section>

                            <section className="panel">
                                <h2>cluster events</h2>
                                <div className="event-log">
                                    {events.length === 0 && <span className="quiet">nothing yet</span>}
                                    {events.slice(-40).map((event, i) => <div key={i}>{event}</div>)}
                                </div>
                            </section>
                        </aside>
                    </div>
                )}

                {header && !summary && frames.length > 0 && (
                    <p className="note">The checks and the numbers show up here when the run ends. Hover the timeline to look at any moment.</p>
                )}

                {summary && verdict && metrics && (
                    <>
                        <div className="columns even">
                            <section className="panel">
                                <h2>checks</h2>
                                <ul className="checks">
                                    {summary.checks.map(check => (
                                        <li key={check.name} className={check.ok === true ? 'good' : check.ok === false ? 'critical' : 'serious'}>
                                            <span className="check-mark">{check.ok === true ? '✓' : check.ok === false ? '✕' : '?'}</span>
                                            <span><b>{check.name}</b>{check.detail}</span>
                                        </li>
                                    ))}
                                </ul>
                            </section>
                            <div className="stack">
                                <section className="panel">
                                    <h2>how fast a lost leader was replaced</h2>
                                    <Detect faults={faults} />
                                </section>
                                <section className="panel">
                                    <h2>how long writes were out for</h2>
                                    <Outages outages={summary.outages} />
                                </section>
                            </div>
                        </div>

                        <section className="panel">
                            <h2>every fault</h2>
                            <div className="table-scroll">
                                <table className="grid-table wide">
                                    <thead><tr><th>what</th><th>kind</th><th>began</th><th>lasted</th><th>noticed after</th><th>new leader after</th><th>out of service</th></tr></thead>
                                    <tbody>
                                        {faults.filter(Boolean).map(fault => (
                                            <tr key={fault.id}>
                                                <td>{fault.label}</td>
                                                <td>{fault.kind}</td>
                                                <td>{fmtTime(fault.t0)}</td>
                                                <td>{fault.t1 === null ? '–' : fmtNum(fault.t1 - fault.t0, 1) + 's'}</td>
                                                {fault.hit_leader
                                                    ? <><td>{fmtMs(fault.detect_ms)}</td><td>{fmtMs(fault.elect_ms)}</td><td>{fmtMs(fault.ots_ms)}</td></>
                                                    : <td colSpan={3} className="quiet">did not take the leader out</td>}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </section>

                        <section className="panel">
                            <h2>what each node held at the end</h2>
                            <div className="table-scroll">
                                <table className="grid-table wide">
                                    <thead><tr><th></th><th>applied up to</th><th>log ends at</th><th>term</th><th>keys</th><th>apply hash</th></tr></thead>
                                    <tbody>
                                        {summary.nodes.map((node, i) => (
                                            <tr key={i}>
                                                <td><span className="line-key" style={{ background: NODE_COLORS[i] }} />node {i}</td>
                                                {node
                                                    ? <><td>{node.applied.toLocaleString()}</td><td>{node.log_idx.toLocaleString()}</td><td>{fmtNum(node.term)}</td><td>{node.keys.toLocaleString()}</td><td>{node.hash}</td></>
                                                    : <td colSpan={5} className="quiet">no reply</td>}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    </>
                )}
            </main>
        </div>
    )
}

export default Debug
