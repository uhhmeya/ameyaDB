import type { Fault } from '../hooks/useRelay.tsx'
import { fmtMs, niceCeil, useWidth } from './scale.ts'

// for every fault that took the leader out: how long until someone noticed,
// until a new leader won, and until a write got through again. three stages of one wait

const ROW_H = 30
const BAR_H = 14
const LABEL_W = 250
const RIGHT = 70

type DetectProps = {
    faults: Fault[]
}

function Detect({ faults }: DetectProps) {
    const { ref, width } = useWidth<HTMLDivElement>()
    const hits = faults.filter(fault => fault && fault.hit_leader).slice(0, 40)
    if (hits.length === 0) return <p className="quiet">no fault took the leader out in this run</p>

    const longest = Math.max(100, ...hits.map(fault => Math.max(fault.detect_ms ?? 0, fault.elect_ms ?? 0, fault.ots_ms ?? 0)))
    const msMax = niceCeil(longest)
    const plotW = Math.max(60, width - LABEL_W - RIGHT)
    const x = (ms: number) => LABEL_W + (Math.min(ms, msMax) / msMax) * plotW
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(share => share * msMax)
    const height = hits.length * ROW_H + 26

    return (
        <div className="detect" ref={ref}>
            <p className="legend">
                <span className="swatch stage-1" /> someone noticed
                <span className="swatch stage-2" /> new leader won
                <span className="swatch stage-3" /> a write got through
            </p>
            {width > 0 && (
                <svg width={width} height={height} role="img" aria-label="time to replace a leader, per fault">
                    {ticks.map(tick => (
                        <g key={tick}>
                            <line className="grid" x1={x(tick)} x2={x(tick)} y1={0} y2={hits.length * ROW_H} />
                            <text className="tick" x={x(tick)} y={hits.length * ROW_H + 16} textAnchor="middle">{fmtMs(tick)}</text>
                        </g>
                    ))}
                    {hits.map((fault, row) => {
                        const y = row * ROW_H + (ROW_H - BAR_H) / 2
                        const noticed = fault.detect_ms ?? null
                        const elected = fault.elect_ms === null || fault.elect_ms === undefined ? null : Math.max(noticed ?? 0, fault.elect_ms)
                        const served = Math.max(elected ?? noticed ?? 0, fault.ots_ms ?? 0)
                        const stages = [
                            { from: 0, to: noticed, name: 'stage-1' },
                            { from: noticed, to: elected, name: 'stage-2' },
                            { from: elected, to: elected === null ? null : served, name: 'stage-3' },
                        ]
                        const tip = elected === null ? 0 : served
                        return (
                            <g key={fault.id}>
                                <title>{`${fault.label}: noticed after ${fmtMs(fault.detect_ms)}, new leader after ${fmtMs(fault.elect_ms)}, out of service ${fmtMs(fault.ots_ms)}`}</title>
                                <rect className="hit" x={0} y={row * ROW_H} width={width} height={ROW_H} />
                                <text className="row-label" x={LABEL_W - 12} y={y + 11} textAnchor="end">
                                    {fault.label.length > 38 ? fault.label.slice(0, 37) + '…' : fault.label}
                                </text>
                                {stages.map(stage => stage.from !== null && stage.to !== null && stage.to > stage.from && (
                                    <rect key={stage.name} className={stage.name} y={y} height={BAR_H} rx={2}
                                          x={x(stage.from) + (stage.from > 0 ? 2 : 0)}
                                          width={Math.max(1, x(stage.to) - x(stage.from) - (stage.from > 0 ? 2 : 0))} />
                                ))}
                                <text className="bar-value" x={x(tip) + 8} y={y + 11}>
                                    {noticed === null ? 'nobody noticed' : elected === null ? 'no new leader' : fmtMs(served)}
                                </text>
                            </g>
                        )
                    })}
                    <line className="baseline" x1={LABEL_W} x2={LABEL_W} y1={0} y2={hits.length * ROW_H} />
                </svg>
            )}
        </div>
    )
}

export default Detect
