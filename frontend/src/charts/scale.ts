import { useEffect, useRef, useState } from 'react'

export const NODE_COLORS = ['var(--n0)', 'var(--n1)', 'var(--n2)', 'var(--n3)', 'var(--n4)']
export const VARIANT_COLORS = ['var(--n0)', 'var(--n1)', 'var(--n2)']

export function niceCeil(value: number): number {
    if (value <= 0) return 1
    const power = Math.pow(10, Math.floor(Math.log10(value)))
    for (const step of [1, 2, 5, 10]) {
        if (step * power >= value) return step * power
    }
    return 10 * power
}

export function nearestFrame(frames: { t: number }[], t: number): number {
    let best = 0
    for (let i = 1; i < frames.length; i++) {
        if (Math.abs(frames[i].t - t) < Math.abs(frames[best].t - t)) best = i
    }
    return best
}

export function timeTicks(tMax: number): number[] {
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find(candidate => tMax / candidate <= 12) ?? 600
    const ticks = []
    for (let t = 0; t <= tMax + 0.001; t += step) ticks.push(t)
    return ticks
}

export function fmtTime(seconds: number): string {
    const whole = Math.max(0, Math.floor(seconds))
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

export function fmtNum(value: number | null | undefined, digits = 0): string {
    if (value === null || value === undefined) return '–'
    const compact = (scaled: number, unit: string) => scaled.toFixed(1).replace(/\.0$/, '') + unit
    if (Math.abs(value) >= 1e9) return compact(value / 1e9, 'B')
    if (Math.abs(value) >= 1e6) return compact(value / 1e6, 'M')
    if (Math.abs(value) >= 1e4) return compact(value / 1e3, 'K')
    return value.toLocaleString('en-US', { maximumFractionDigits: digits })
}

export function fmtMs(ms: number | null | undefined): string {
    if (ms === null || ms === undefined) return 'never'
    return ms >= 10000 ? (ms / 1000).toFixed(0) + 's' : ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms) + 'ms'
}

export function fmtPct(share: number | null | undefined): string {
    if (share === null || share === undefined) return '–'
    return (share * 100).toFixed(1).replace(/\.0$/, '') + '%'
}

export function linePath(points: [number, number][]): string {
    return points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join('')
}

export function stepPath(points: [number, number][]): string {
    let path = ''
    points.forEach(([x, y], i) => {
        path += i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `H${x.toFixed(1)}V${y.toFixed(1)}`
    })
    return path
}

export function useWidth<Box extends HTMLElement>() {
    const ref = useRef<Box | null>(null)
    const [width, setWidth] = useState(0)

    useEffect(() => {
        if (!ref.current) return
        const observer = new ResizeObserver(entries => {
            if (!window.matchMedia('print').matches) setWidth(entries[0].contentRect.width)
        })
        observer.observe(ref.current)
        return () => observer.disconnect()
    }, [])

    return { ref, width }
}
