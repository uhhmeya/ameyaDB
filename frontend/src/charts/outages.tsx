import type { Summary } from '../hooks/useRelay.tsx'
import { niceCeil, useWidth } from './scale.ts'

// every stretch with no acked write, sorted by how long it lasted. the bar is the time
// lost in that row, because fifty short blips can cost less than one long stall

const BUCKETS = [
    { under: 0.2, name: 'under 200ms' },
    { under: 0.5, name: '200 to 500ms' },
    { under: 1, name: '0.5 to 1s' },
    { under: 2, name: '1 to 2s' },
    { under: 5, name: '2 to 5s' },
    { under: 10, name: '5 to 10s' },
    { under: Infinity, name: 'over 10s' },
]
const ROW_H = 26
const BAR_H = 12
const LABEL_W = 104
const RIGHT = 150

type OutagesProps = {
    outages: Summary['outages']
}

function fmtSecs(seconds: number): string {
    return (seconds < 10 ? seconds.toFixed(2) : seconds.toFixed(1)) + 's'
}

function Outages({ outages }: OutagesProps) {
    const { ref, width } = useWidth<HTMLDivElement>()
    if (outages.length === 0) return <p className="quiet">writes never stopped for longer than 100ms</p>

    const rows = BUCKETS.map(bucket => ({ ...bucket, count: 0, avoidable: 0, unavoidable: 0 }))
    for (const [t0, t1, avoidable] of outages) {
        const row = rows.find(row => t1 - t0 < row.under)!
        row.count++
        row.avoidable += avoidable
        row.unavoidable += t1 - t0 - avoidable
    }

    const secsMax = niceCeil(Math.max(...rows.map(row => row.avoidable + row.unavoidable)))
    const plotW = Math.max(60, width - LABEL_W - RIGHT)
    const x = (seconds: number) => LABEL_W + (seconds / secsMax) * plotW
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(share => share * secsMax)
    const height = rows.length * ROW_H + 26

    return (
        <div className="outages" ref={ref}>
            <p className="legend">
                <span><span className="swatch outage" /> some node could have led</span>
                <span><span className="swatch outage unavoidable" /> nobody could lead</span>
            </p>
            {width > 0 && (
                <svg width={width} height={height} role="img" aria-label="seconds without an acked write, by how long each outage lasted">
                    {ticks.map(tick => (
                        <g key={tick}>
                            <line className="grid" x1={x(tick)} x2={x(tick)} y1={0} y2={rows.length * ROW_H} />
                            <text className="tick" x={x(tick)} y={rows.length * ROW_H + 16} textAnchor="middle">{+tick.toFixed(2)}s</text>
                        </g>
                    ))}
                    {rows.map((row, i) => {
                        const y = i * ROW_H + (ROW_H - BAR_H) / 2
                        const total = row.avoidable + row.unavoidable
                        const split = x(row.avoidable)
                        return (
                            <g key={row.name}>
                                <title>{`${row.count} outages lasting ${row.name}: ${fmtSecs(total)} lost, ${fmtSecs(row.avoidable)} of it while some node could have led`}</title>
                                <rect className="hit" x={0} y={i * ROW_H} width={width} height={ROW_H} />
                                <text className="row-label" x={LABEL_W - 12} y={y + 10} textAnchor="end">{row.name}</text>
                                {row.avoidable > 0 && (
                                    <rect className="outage" x={LABEL_W} y={y} width={Math.max(1, split - LABEL_W)} height={BAR_H} rx={2} />
                                )}
                                {row.unavoidable > 0 && (
                                    <rect className="outage unavoidable" y={y} height={BAR_H} rx={2}
                                          x={split + (row.avoidable > 0 ? 2 : 0)}
                                          width={Math.max(1, x(total) - split - (row.avoidable > 0 ? 2 : 0))} />
                                )}
                                {row.count > 0 && (
                                    <text className="bar-value" x={x(total) + 8} y={y + 10}>{row.count} {row.count === 1 ? 'outage' : 'outages'}, {fmtSecs(total)}</text>
                                )}
                            </g>
                        )
                    })}
                    <line className="baseline" x1={LABEL_W} x2={LABEL_W} y1={0} y2={rows.length * ROW_H} />
                </svg>
            )}
        </div>
    )
}

export default Outages
