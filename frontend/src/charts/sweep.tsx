import { useState } from 'react'
import type { PointerEvent } from 'react'
import { VARIANT_COLORS, linePath, niceCeil, useWidth } from './scale.ts'

const LEFT = 88
const RIGHT = 150
const TOP = 14
const PLOT_H = 250

export type SweepSeries = {
    label: string
    points: { x: number, y: number | null, lo: number | null, hi: number | null, runs: number }[]
}

type SweepChartProps = {
    xName: string
    yName: string
    series: SweepSeries[]
    ideal: { x: number, y: number }[] | null
    format: (value: number) => string
    yMax: number | null
}

function SweepChart({ xName, yName, series, ideal, format, yMax }: SweepChartProps) {
    const { ref, width } = useWidth<HTMLDivElement>()
    const [hoverX, setHoverX] = useState<number | null>(null)

    const xs = Array.from(new Set(series.flatMap(line => line.points.map(point => point.x)))).sort((a, b) => a - b)
    if (xs.length === 0) return <p className="quiet">no finished runs for this sweep yet</p>

    const ys = series.flatMap(line => line.points.flatMap(point => [point.y, point.hi])).filter((y): y is number => y !== null)
    const top = yMax ?? niceCeil(Math.max(1e-9, ...ys))
    const narrow = width < 560
    const plotW = Math.max(80, width - LEFT - (narrow ? 24 : RIGHT))
    const xLo = xs[0], xHi = xs[xs.length - 1] === xs[0] ? xs[0] + 1 : xs[xs.length - 1]
    const x = (value: number) => LEFT + ((value - xLo) / (xHi - xLo)) * plotW
    const y = (value: number) => TOP + PLOT_H - (Math.min(value, top) / top) * PLOT_H
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map(share => share * top)
    const height = TOP + PLOT_H + 48

    const ends = series.map(line => line.points.filter(point => point.y !== null).slice(-1)[0])
    const endsCollide = ends.some((end, i) => ends.some((other, j) => i < j && end && other
        && Math.abs(y(end.y as number) - y(other.y as number)) < 15))

    function onPointerMove(event: PointerEvent<SVGSVGElement>) {
        const box = event.currentTarget.getBoundingClientRect()
        const at = xLo + ((event.clientX - box.left - LEFT) / plotW) * (xHi - xLo)
        setHoverX(xs.reduce((best, value) => Math.abs(value - at) < Math.abs(best - at) ? value : best, xs[0]))
    }

    return (
        <div className="sweep-chart" ref={ref}>
            <p className="legend">
                {series.map((line, i) => (
                    <span key={line.label}><span className="line-key" style={{ background: VARIANT_COLORS[i] }} /> {line.label}</span>
                ))}
                {ideal && <span><span className="line-key dashed" /> best any protocol could do</span>}
            </p>
            {width > 0 && (
                <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`each variant against ${xName}`}
                     onPointerMove={onPointerMove} onPointerLeave={() => setHoverX(null)}>
                    {yTicks.map(tick => (
                        <g key={tick}>
                            <line className="grid" x1={LEFT} x2={LEFT + plotW} y1={y(tick)} y2={y(tick)} />
                            <text className="tick" x={LEFT - 8} y={y(tick) + 4} textAnchor="end">{format(tick)}</text>
                        </g>
                    ))}
                    <text className="axis-name" x={0} y={0} textAnchor="middle" transform={`translate(14, ${TOP + PLOT_H / 2}) rotate(-90)`}>{yName}</text>
                    {xs.map(value => <text key={value} className="tick" x={x(value)} y={TOP + PLOT_H + 18} textAnchor="middle">{value}</text>)}
                    <text className="axis-name" x={LEFT + plotW / 2} y={TOP + PLOT_H + 40} textAnchor="middle">{xName}</text>
                    <line className="baseline" x1={LEFT} x2={LEFT + plotW} y1={y(0)} y2={y(0)} />

                    {ideal && <path className="line ideal" d={linePath(ideal.map(point => [x(point.x), y(point.y)]))} />}

                    {series.map((line, i) => {
                        const drawn = line.points.filter(point => point.y !== null)
                        return (
                            <g key={line.label}>
                                {drawn.map(point => point.runs > 1 && point.lo !== null && point.hi !== null && (
                                    <line key={point.x} className="whisker" stroke={VARIANT_COLORS[i]} x1={x(point.x)} x2={x(point.x)} y1={y(point.lo)} y2={y(point.hi)} />
                                ))}
                                <path className="line" stroke={VARIANT_COLORS[i]} d={linePath(drawn.map(point => [x(point.x), y(point.y as number)]))} />
                                {drawn.map(point => (
                                    <circle key={point.x} className="marker" fill={VARIANT_COLORS[i]} cx={x(point.x)} cy={y(point.y as number)} r={hoverX === point.x ? 6 : 4.5} />
                                ))}
                                {!narrow && !endsCollide && series.length <= 4 && drawn.length > 0 && (
                                    <text className="end-label" x={x(drawn[drawn.length - 1].x) + 10} y={y(drawn[drawn.length - 1].y as number) + 4}>{line.label}</text>
                                )}
                            </g>
                        )
                    })}

                    {hoverX !== null && <line className="cursor" x1={x(hoverX)} x2={x(hoverX)} y1={TOP} y2={TOP + PLOT_H} />}
                </svg>
            )}
            {hoverX !== null && (
                <div className="readout" style={x(hoverX) > width - 300 ? { right: width - x(hoverX) + 14 } : { left: x(hoverX) + 14 }}>
                    <div className="readout-time">{xName} <span>{hoverX}</span></div>
                    {series.map((line, i) => {
                        const point = line.points.find(point => point.x === hoverX)
                        return (
                            <div key={line.label}>
                                <span className="line-key" style={{ background: VARIANT_COLORS[i] }} />{' '}
                                <b>{point && point.y !== null ? format(point.y) : '–'}</b> {line.label}
                            </div>
                        )
                    })}
                    {ideal && ideal.some(point => point.x === hoverX) && (
                        <div><span className="line-key dashed" /> <b>{format(ideal.find(point => point.x === hoverX)!.y)}</b> best possible</div>
                    )}
                </div>
            )}
        </div>
    )
}

export default SweepChart
