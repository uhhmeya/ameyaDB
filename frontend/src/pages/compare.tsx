import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Catalog, ShortRun, Sweep } from '../hooks/useRelay.tsx'
import SweepChart from '../charts/sweep.tsx'
import type { SweepSeries } from '../charts/sweep.tsx'
import { fmtMs, fmtNum, fmtPct } from '../charts/scale.ts'

// the page a paper's figures come from: the same sweep, run once per variant of the protocol

const METRICS = [
    { key: 'availability', name: 'share of the time writes got through', format: fmtPct, yMax: 1 },
    { key: 'goodput', name: 'share of the healthy write rate that survived', format: fmtPct, yMax: null },
    { key: 'oos_avoidable', name: 'seconds down while some node could have led', format: (v: number) => fmtNum(v, 1) + 's', yMax: null },
    { key: 'elections_per_min', name: 'elections started per minute', format: (v: number) => fmtNum(v, 1), yMax: null },
    { key: 'term_growth', name: 'terms burned', format: (v: number) => fmtNum(v), yMax: null },
    { key: 'prevotes', name: 'pre-vote rounds started', format: (v: number) => fmtNum(v), yMax: null },
    { key: 'writes_per_sec', name: 'writes acked per second', format: (v: number) => fmtNum(v), yMax: null },
    { key: 'p99', name: 'p99 write latency', format: (v: number) => fmtMs(v), yMax: null },
    { key: 'ots_ms', name: 'out of service time per lost leader', format: (v: number) => fmtMs(v), yMax: null },
    { key: 'detect_ms', name: 'time to notice a lost leader', format: (v: number) => fmtMs(v), yMax: null },
    { key: 'recover_sec', name: 'seconds to serve writes again after the heal', format: (v: number) => fmtNum(v, 2) + 's', yMax: null },
]

type CompareProps = {
    history: ShortRun[]
    sweep: Sweep | null
    catalog: Catalog | null
}

function mean(values: number[]) {
    return values.reduce((sum, value) => sum + value, 0) / values.length
}

function Compare({ history, sweep, catalog }: CompareProps) {
    const trials = history.filter(run => run.sweep)
    const names = Array.from(new Set(trials.map(run => run.name)))
    const [pickedName, setPickedName] = useState<string | null>(null)
    const [metricKey, setMetricKey] = useState('availability')

    const name = pickedName ?? sweep?.name ?? names[names.length - 1] ?? null
    const metric = METRICS.find(metric => metric.key === metricKey) ?? METRICS[0]
    const about = catalog?.sweeps.find(entry => entry.name === name)
    const mine = trials.filter(run => run.name === name)

    // colour follows the variant: baseline is always the first colour, the rest in the order they first ran
    const labels = Array.from(new Set(mine.map(run => run.label))).sort((a, b) => Number(b === 'baseline') - Number(a === 'baseline'))
    const shown = labels.slice(0, 3)
    const xs = Array.from(new Set(mine.map(run => run.x as number | string)))
    const isNumeric = xs.every(x => typeof x === 'number')
    if (isNumeric) xs.sort((a, b) => (a as number) - (b as number))

    const valuesAt = (label: string, x: number | string, key: string) =>
        mine.filter(run => run.label === label && run.x === x).map(run => run.metrics[key]).filter((value): value is number => value !== null && value !== undefined)

    const series: SweepSeries[] = shown.map(label => ({
        label,
        points: (xs as number[]).map(x => {
            const values = valuesAt(label, x, metric.key)
            return values.length
                ? { x, y: mean(values), lo: Math.min(...values), hi: Math.max(...values), runs: values.length }
                : { x, y: null, lo: null, hi: null, runs: 0 }
        }),
    }))

    // one row per run with every number it produced, for making the paper's figures somewhere else
    function downloadCsv() {
        const metrics = Array.from(new Set(mine.flatMap(run => Object.keys(run.metrics))))
        const head = ['sweep', 'variant', 'x', 'run', 'seed', 'verdict', 'passed', ...metrics]
        const rows = mine.map(run => [
            run.name, `"${run.label.replace(/"/g, '""')}"`, run.x, run.id, run.seed, run.verdict, run.passed,
            ...metrics.map(key => run.metrics[key] ?? ''),
        ])
        const blob = new Blob([[head, ...rows].map(row => row.join(',')).join('\n')], { type: 'text/csv' })
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob)
        link.download = `${name}.csv`
        link.click()
        URL.revokeObjectURL(link.href)
    }

    const idealAt = (x: number | string) => mine.find(run => run.x === x && run.metrics.ideal !== undefined)?.metrics.ideal
    const ideal = name === 'links' && metric.key === 'availability' && isNumeric
        ? (xs as number[]).filter(x => typeof idealAt(x) === 'number').map(x => ({ x, y: idealAt(x) as number }))
        : null

    return (
        <div className="board">
            <header className="bar">
                <nav><Link to="/run">run</Link><Link to="/debug">live</Link><Link to="/compare" className="here">compare</Link></nav>
                <h1>compare variants</h1>
                {mine.length > 0 && <div className="bar-right"><button onClick={downloadCsv}>download these runs as csv</button></div>}
            </header>

            {names.length === 0 ? (
                <p className="empty">
                    No sweep has finished a run yet. <Link to="/run">Start a sweep</Link>, then run the same sweep again
                    with a different variant switched on. Every variant becomes one line here.
                </p>
            ) : (
                <section className="sheet">
                    <div className="filters">
                        <label>sweep
                            <select value={name ?? ''} onChange={event => setPickedName(event.target.value)}>
                                {names.map(option => <option key={option}>{option}</option>)}
                            </select>
                        </label>
                        <label>measure
                            <select value={metric.key} onChange={event => setMetricKey(event.target.value)}>
                                {METRICS.map(option => <option key={option.key} value={option.key}>{option.name}</option>)}
                            </select>
                        </label>
                    </div>
                    <h2>{metric.name}</h2>
                    <p className="about">{about?.about}</p>
                    {labels.length > 3 && <p className="about">showing {shown.join(', ')}. {labels.length - 3} more variants are in the table below.</p>}

                    {isNumeric && <SweepChart xName={about?.x_name ?? 'x'} series={series} ideal={ideal} format={metric.format} yMax={metric.yMax} />}

                    <table className="grid-table">
                        <thead>
                            <tr>
                                <th>{about?.x_name ?? 'x'}</th>
                                {labels.map(label => <th key={label}>{label}</th>)}
                                {ideal && <th>best possible</th>}
                            </tr>
                        </thead>
                        <tbody>
                            {xs.map(x => (
                                <tr key={String(x)}>
                                    <td>{x}</td>
                                    {labels.map(label => {
                                        const values = valuesAt(label, x, metric.key)
                                        const failed = mine.some(run => run.label === label && run.x === x && !run.passed)
                                        return (
                                            <td key={label}>
                                                {metric.key === 'availability' && values.length > 0 && (
                                                    <span className="meter"><span style={{ width: `${mean(values) * 100}%` }} /></span>
                                                )}
                                                {values.length ? metric.format(mean(values)) : '–'}
                                                {values.length > 1 && <span className="quiet"> ×{values.length}</span>}
                                                {failed && <span className="flag" title="a check failed in at least one of these runs"> ✕ check failed</span>}
                                            </td>
                                        )
                                    })}
                                    {ideal && <td>{typeof idealAt(x) === 'number' ? metric.format(idealAt(x) as number) : '–'}</td>}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>
            )}
        </div>
    )
}

export default Compare
