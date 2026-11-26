import type { KeyboardEvent, PointerEvent } from 'react'
import type { Fault, Frame, Recording, TimelineEvent } from '../hooks/useRelay.tsx'
import { NUM_NODES } from '../hooks/useRelay.tsx'
import { NODE_COLORS, fmtNum, fmtTime, linePath, nearestFrame, niceCeil, stepPath, timeTicks, useWidth } from './scale.ts'

const LEFT = 132
const RIGHT = 18
const GAP = 20
const LANE_H = 20
const FAULT_H = 18

type Role = 'down' | 'follower' | 'precandidate' | 'candidate' | 'leader'

type Stretch = {
    t0: number
    t1: number
    role: Role
    term: number
}

type TracksProps = {
    recording: Recording
    cursor: number | null
    setCursor: (t: number | null) => void
}

function stretchesOf(events: TimelineEvent[], node: number, tEnd: number): Stretch[] {
    const stretches: Stretch[] = []
    let role: Role = 'down'
    let since = 0
    let term = 0

    for (const [t, eventNode, kind, eventTerm] of events) {
        if (eventNode !== node) continue

        let next: Role | null = null
        if (kind === 'follower' || kind === 'precandidate' || kind === 'candidate' || kind === 'leader') next = kind
        else if (kind === 'down' || kind === 'cut') next = 'down'
        else if (kind === 'up') next = 'follower'
        if (next === null || (next === role && eventTerm === term)) continue

        if (t > since) stretches.push({ t0: since, t1: t, role, term })
        role = next
        since = Math.max(since, t)
        term = eventTerm
    }
    if (tEnd > since) stretches.push({ t0: since, t1: tEnd, role, term })
    return stretches
}

function rowsOf(faults: Fault[], tEnd: number): Fault[][] {
    const rows: Fault[][] = []
    const sorted = faults.filter(Boolean).slice().sort((a, b) => a.t0 - b.t0)
    for (const fault of sorted) {
        const row = rows.find(row => (row[row.length - 1].t1 ?? tEnd) <= fault.t0)
        if (row) row.push(fault)
        else rows.push([fault])
    }
    return rows
}

function Tracks({ recording, cursor, setCursor }: TracksProps) {
    const { ref, width } = useWidth<HTMLDivElement>()
    const { frames, events, faults, summary } = recording

    const tNow = frames.length ? frames[frames.length - 1].t : 0
    const tMax = Math.max(10, tNow)
    const plotW = Math.max(100, width - LEFT - RIGHT)
    const x = (t: number) => LEFT + (Math.min(t, tMax) / tMax) * plotW

    const sortedEvents = events.slice().sort((a, b) => a[0] - b[0])
    const lanes = Array.from({ length: NUM_NODES }, (_, node) => stretchesOf(sortedEvents, node, tNow))
    const faultRows = rowsOf(faults, tNow)

    let nextY = 14
    const place = (height: number) => {
        const top = nextY
        nextY += height + GAP
        return top
    }
    const faultsY = place(Math.max(1, faultRows.length) * FAULT_H)
    const lanesY = place(NUM_NODES * LANE_H)
    const serviceY = place(14)
    const termH = 76, termY = place(termH)
    const writesH = 76, writesY = place(writesH)
    const latH = 76, latY = place(latH)
    const lagH = 64, lagY = place(lagH)
    const votesH = 40, votesY = place(votesH)
    const axisY = nextY - GAP + 6
    const height = axisY + 42

    const terms = frames.flatMap(frame => frame.nodes.map(node => node.term ?? null)).filter((term): term is number => term !== null)
    const termLo = terms.length ? Math.min(...terms) : 0
    const termHi = Math.max(termLo + 4, terms.length ? Math.max(...terms) : 4)
    const termYOf = (term: number) => termY + termH - ((term - termLo) / (termHi - termLo)) * termH

    const perSec = (count: number, i: number) => count / Math.max(0.1, i === 0 ? frames[0].t : frames[i].t - frames[i - 1].t)
    const acked = frames.map((frame, i) => perSec(frame.ok, i))
    const failed = frames.map((frame, i) => perSec(frame.idk + frame.timeout, i))
    const writesHi = niceCeil(Math.max(10, ...acked, ...failed))
    const writesYOf = (value: number) => writesY + writesH - (value / writesHi) * writesH

    const latHi = Math.max(100, niceCeil(Math.max(1, ...frames.map(frame => frame.p99 ?? 0))))
    const LAT_LO = 0.1
    const latYOf = (ms: number) => latY + latH - (Math.log10(Math.max(LAT_LO, ms) / LAT_LO) / Math.log10(latHi / LAT_LO)) * latH
    const latTicks = [1, 10, 100, 1000, 10000].filter(tick => tick <= latHi)

    const lagOf = (frame: Frame, node: number) => {
        const commits = frame.nodes.filter(other => other.up && other.commit !== undefined).map(other => other.commit as number)
        const mine = frame.nodes[node]
        if (!mine.up || mine.commit === undefined || commits.length === 0) return null
        return Math.max(...commits) - mine.commit
    }
    const lagHi = Math.max(100, niceCeil(Math.max(1, ...frames.flatMap(frame => frame.nodes.map((_, node) => lagOf(frame, node) ?? 0)))))
    const lagYOf = (lag: number) => lagY + lagH - (Math.log10(1 + lag) / Math.log10(1 + lagHi)) * lagH

    const votesHi = niceCeil(Math.max(5, ...frames.map(frame => frame.vreq)))

    const nodeLines = (valueOf: (frame: Frame, node: number) => number | null, yOf: (value: number) => number, step: boolean) =>
        Array.from({ length: NUM_NODES }, (_, node) => {
            const pieces: [number, number][][] = [[]]
            for (const frame of frames) {
                const value = valueOf(frame, node)
                if (value === null) pieces.push([])
                else pieces[pieces.length - 1].push([x(frame.t), yOf(value)])
            }
            return pieces.filter(piece => piece.length > 1).map(piece => step ? stepPath(piece) : linePath(piece)).join('')
        })

    const termLines = nodeLines((frame, node) => frame.nodes[node].up ? frame.nodes[node].term ?? null : null, termYOf, true)
    const lagLines = nodeLines(lagOf, lagYOf, false)

    const outages: { t0: number, t1: number, avoidable: boolean }[] = []
    if (summary) {
        for (const [t0, t1, avoidable] of summary.outages) outages.push({ t0, t1, avoidable: avoidable > (t1 - t0) / 2 })
    } else {
        frames.forEach((frame, i) => {
            if (frame.served === 0 && i > 0 && frame.phase !== 'reset') outages.push({ t0: frames[i - 1].t, t1: frame.t, avoidable: frame.viable })
        })
    }

    const phaseStarts = frames.filter((frame, i) => i === 0 || frame.phase !== frames[i - 1].phase)
    const phases = phaseStarts.filter((frame, i) => {
        const roomUntil = i + 1 < phaseStarts.length ? x(phaseStarts[i + 1].t) : LEFT + plotW
        return roomUntil - x(frame.t) > frame.phase.length * 6 + 8
    })
    const cursorAt = cursor !== null && frames.length ? nearestFrame(frames, cursor) : null
    const cursorFrame = cursorAt === null ? null : frames[cursorAt]
    const cursorFaults = cursor === null ? [] : faults.filter(fault => fault && fault.t0 <= cursor && (fault.t1 ?? tNow) >= cursor)

    function onPointerMove(event: PointerEvent<SVGSVGElement>) {
        const box = event.currentTarget.getBoundingClientRect()
        const t = ((event.clientX - box.left - LEFT) / plotW) * tMax
        setCursor(t < 0 || t > tMax ? null : t)
    }

    function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
        if (!frames.length || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return
        const at = nearestFrame(frames, cursor ?? tNow)
        const next = Math.min(frames.length - 1, Math.max(0, at + (event.key === 'ArrowRight' ? 1 : -1)))
        setCursor(frames[next].t)
        event.preventDefault()
    }

    const trackName = (name: string, y: number, note?: string) => (
        <>
            <text className="track-name" x={0} y={y + 11}>{name}</text>
            {note && <text className="track-note" x={0} y={y + 25}>{note}</text>}
        </>
    )
    const yTick = (label: string, y: number) => (
        <>
            <line className="grid" x1={LEFT} x2={LEFT + plotW} y1={y} y2={y} />
            <text className="tick" x={LEFT - 8} y={y + 4} textAnchor="end">{label}</text>
        </>
    )

    return (
        <div className="tracks" ref={ref}>
            {width > 0 && (
                <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" tabIndex={0}
                     aria-label="timeline of the run: faults, what each node was doing, and how the cluster served writes"
                     onPointerMove={onPointerMove} onPointerLeave={() => setCursor(null)} onKeyDown={onKeyDown}>

                    {timeTicks(tMax).map(t => (
                        <g key={t}>
                            <line className="grid" x1={x(t)} x2={x(t)} y1={faultsY} y2={axisY} />
                            <text className="tick" x={x(t)} y={axisY + 16} textAnchor="middle">{fmtTime(t)}</text>
                        </g>
                    ))}
                    <text className="axis-name" x={LEFT + plotW / 2} y={axisY + 36} textAnchor="middle">time since the run began</text>
                    {phases.map(frame => (
                        <text key={frame.t} className="phase" x={x(Math.max(0, frame.t - 0.5)) + 3} y={9}>{frame.phase}</text>
                    ))}

                    {trackName('faults', faultsY)}
                    {faultRows.map((row, rowNum) => row.map(fault => {
                        const x0 = x(fault.t0), x1 = x(fault.t1 ?? tNow)
                        const w = Math.max(3, x1 - x0 - 2)
                        return (
                            <g key={fault.id}>
                                <rect className={fault.hit_leader ? 'fault hit-leader' : 'fault'} x={x0} y={faultsY + rowNum * FAULT_H} width={w} height={FAULT_H - 4} rx={3}>
                                    <title>{fault.label}</title>
                                </rect>
                                {w > fault.label.length * 6.1 + 10 && (
                                    <text className={fault.hit_leader ? 'fault-label on-accent' : 'fault-label'} x={x0 + 6} y={faultsY + rowNum * FAULT_H + 10.5}>{fault.label}</text>
                                )}
                            </g>
                        )
                    }))}

                    {lanes.map((stretches, node) => {
                        const mid = lanesY + node * LANE_H + LANE_H / 2
                        return (
                            <g key={node}>
                                <text className="track-name" x={0} y={mid + 4}>node {node}</text>
                                <line className="lane-rail" x1={LEFT} x2={LEFT + plotW} y1={mid} y2={mid} />
                                {stretches.map((stretch, i) => {
                                    if (stretch.role === 'down') return null
                                    const thick = stretch.role === 'leader' ? 14 : stretch.role === 'follower' ? 2 : 7
                                    const x0 = x(stretch.t0), w = Math.max(1.5, x(stretch.t1) - x0 - (stretch.role === 'follower' ? 0 : 2))
                                    const hollow = stretch.role === 'precandidate'
                                    return (
                                        <g key={i}>
                                            <rect x={x0} y={mid - thick / 2} width={w} height={thick} rx={stretch.role === 'follower' ? 0 : 3}
                                                  fill={hollow ? 'none' : NODE_COLORS[node]} stroke={hollow ? NODE_COLORS[node] : 'none'} strokeWidth={1.5}
                                                  opacity={stretch.role === 'candidate' ? 0.55 : 1} />
                                            {stretch.role === 'leader' && w > 34 && (
                                                <text className="in-bar" x={x0 + 5} y={mid + 3.5}>t{fmtNum(stretch.term)}</text>
                                            )}
                                        </g>
                                    )
                                })}
                            </g>
                        )
                    })}

                    {trackName('service', serviceY)}
                    <line className="serving" x1={LEFT} x2={x(tNow)} y1={serviceY + 7} y2={serviceY + 7} />
                    {outages.map((outage, i) => (
                        <rect key={i} className={outage.avoidable ? 'outage' : 'outage unavoidable'}
                              x={x(outage.t0)} y={serviceY} width={Math.max(2, x(outage.t1) - x(outage.t0))} height={14} rx={2}>
                            <title>{`no write acked for ${(outage.t1 - outage.t0).toFixed(2)}s, ${outage.avoidable ? 'though some node could reach a majority' : 'no node could reach a majority'}`}</title>
                        </rect>
                    ))}

                    {trackName('term', termY, 'per node')}
                    {yTick(fmtNum(termHi), termY)}
                    {yTick(fmtNum(termLo), termY + termH)}
                    {termLines.map((path, node) => <path key={node} className="line" d={path} stroke={NODE_COLORS[node]} />)}

                    {trackName('writes / s', writesY, 'acked, failed')}
                    {yTick(fmtNum(writesHi), writesY)}
                    {yTick('0', writesY + writesH)}
                    {frames.length > 1 && (
                        <>
                            <path className="wash" d={linePath(frames.map((frame, i) => [x(frame.t), writesYOf(acked[i])])) + `L${x(tNow)},${writesY + writesH}L${x(frames[0].t)},${writesY + writesH}Z`} />
                            <path className="line ink" d={linePath(frames.map((frame, i) => [x(frame.t), writesYOf(acked[i])]))} />
                            <path className="line bad" d={linePath(frames.map((frame, i) => [x(frame.t), writesYOf(failed[i])]))} />
                        </>
                    )}

                    {trackName('latency', latY, 'p50, p99 (log)')}
                    {latTicks.map(tick => <g key={tick}>{yTick(tick >= 1000 ? `${tick / 1000}s` : `${tick}ms`, latYOf(tick))}</g>)}
                    {(['p50', 'p99'] as const).map(which => {
                        const pieces: [number, number][][] = [[]]
                        for (const frame of frames) {
                            const ms = frame[which]
                            if (ms === null) pieces.push([])
                            else pieces[pieces.length - 1].push([x(frame.t), latYOf(ms)])
                        }
                        return <path key={which} className={which === 'p99' ? 'line ink' : 'line ink-dim'} d={pieces.filter(piece => piece.length > 1).map(linePath).join('')} />
                    })}

                    {trackName('behind by', lagY, 'entries (log)')}
                    {yTick(fmtNum(lagHi), lagY)}
                    {yTick('0', lagY + lagH)}
                    {lagLines.map((path, node) => <path key={node} className="line" d={path} stroke={NODE_COLORS[node]} />)}

                    {trackName('vote reqs', votesY, 'per tick')}
                    {yTick(fmtNum(votesHi), votesY)}
                    <line className="baseline" x1={LEFT} x2={LEFT + plotW} y1={votesY + votesH} y2={votesY + votesH} />
                    {frames.map((frame, i) => frame.vreq > 0 && (
                        <rect key={i} className="vote-bar" x={x(frame.t) - 1.5} width={3} rx={1.5}
                              y={votesY + votesH - Math.min(1, frame.vreq / votesHi) * votesH} height={Math.min(1, frame.vreq / votesHi) * votesH} />
                    ))}

                    {cursor !== null && <line className="cursor" x1={x(cursor)} x2={x(cursor)} y1={4} y2={axisY} />}
                </svg>
            )}

            {cursor !== null && cursorFrame && (
                <div className="readout" style={x(cursor) > width - 290 ? { right: width - x(cursor) + 14 } : { left: x(cursor) + 14 }}>
                    <div className="readout-time">{fmtTime(cursorFrame.t)} <span>{cursorFrame.phase}</span></div>
                    <div><b>{fmtNum(acked[cursorAt ?? 0])}</b> writes / s</div>
                    <div><b>{cursorFrame.p99 === null ? '–' : cursorFrame.p99.toFixed(1) + 'ms'}</b> p99</div>
                    <div><b>{cursorFrame.served === 0 ? 'no' : 'yes'}</b> serving writes</div>
                    {cursorFaults.map(fault => <div key={fault.id} className="readout-fault">{fault.label}</div>)}
                </div>
            )}
        </div>
    )
}

export default Tracks
