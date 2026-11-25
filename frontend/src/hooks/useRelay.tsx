import { useEffect, useRef, useState } from 'react'

// `VITE_RELAY_URL=ws://127.0.0.1:8765 npm run dev` points the page at a relay somewhere else
const RELAY_URL: string = import.meta.env.VITE_RELAY_URL ?? "ws://107.20.154.53:8765"
const INITIAL_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 5000

export const NUM_NODES = 5

// ---- what test.py sends, see make_frame() and judge_run() in test.py

export type NodeNow = {
    up: number // 0 down, 1 fine, 2 process is there but has gone quiet (frozen or limping)
    role?: number // 0 follower, 1 candidate, 2 leader, 3 asking for pre-votes
    term?: number
    commit?: number
    conn?: number // bit n is set when this node has a live tcp wire to node n
}

// [seconds since the run began, node, what happened, term]
export type TimelineEvent = [number, number, string, number]

export type Fault = {
    id: number
    label: string
    kind: string
    nodes: number[]
    t0: number
    t1: number | null
    hit_leader: boolean
    victim: number | null
    hit_at?: number
    detect_ms?: number | null
    elect_ms?: number | null
    ots_ms?: number | null
}

export type Frame = {
    t: number
    phase: string
    nodes: NodeNow[]
    ok: number
    redirect: number
    idk: number
    timeout: number
    p50: number | null
    p99: number | null
    max: number | null
    served: number
    viable: boolean
    links: string // 25 chars, row = sender, column = receiver. 0 fine, 1 firewall cut, 2 all msgs dropped, 3 lossy, 4 slow
    vreq: number
    ev: TimelineEvent[]
    fx: Fault[]
}

export type RunHeader = {
    id: string
    mode: string
    name: string
    label: string
    flags: Record<string, number>
    seed: number
    seconds: number
    hard: boolean
    sweep: string | null
    x: number | string | null
}

export type Check = {
    name: string
    ok: boolean | null
    detail: string
}

export type Metrics = Record<string, number | null>

export type ShortRun = RunHeader & {
    verdict: string
    passed: boolean
    metrics: Metrics
}

export type NodeAtEnd = {
    applied: number
    term: number
    keys: number
    digest: string
    hash: string
    log_idx: number
}

export type Summary = {
    verdict: string
    passed: boolean
    unsafe: boolean
    checks: Check[]
    metrics: Metrics
    short: ShortRun
    nodes: (NodeAtEnd | null)[]
    faults: Fault[]
    window: [number, number, number] // faults began, healed, measuring stopped
    outages: [number, number, number][] // start, end, seconds of it a leader was possible
}

export type SweepPoint = Metrics & {
    x: number | string
    run: string
    verdict: string
    passed: boolean
}

export type Sweep = {
    id: string
    name: string
    about: string
    x_name: string
    xs: (number | string)[]
    label: string
    flags: Record<string, number>
    seconds: number
    hard: boolean
    points: SweepPoint[]
}

export type Catalog = {
    scenarios: { name: string, about: string, seconds: number }[]
    sweeps: { name: string, about: string, x_name: string, xs: (number | string)[] }[]
}

export type ClusterStatus = {
    bornDeadOrParticipating: number
    compileFailed: boolean
    busy: boolean
}

// everything needed to draw one run, live or from a saved file
export type Recording = {
    header: RunHeader | null
    frames: Frame[]
    events: TimelineEvent[]
    faults: Fault[]
    summary: Summary | null
}

function emptyRecording(header: RunHeader | null): Recording {
    return { header, frames: [], events: [], faults: [], summary: null }
}

function addFrame(recording: Recording, frame: Frame) {
    recording.frames.push(frame)
    for (const event of frame.ev) recording.events.push(event)
    for (const fault of frame.fx) recording.faults[fault.id] = fault
}

export function useRelay() {
    const wsRef = useRef<WebSocket | null>(null)
    const backoffRef = useRef(INITIAL_BACKOFF_MS)
    const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const cancelledRef = useRef(false)

    // frames arrive twice a second for minutes. they pile up in refs and the page redraws once per animation frame
    const recordingRef = useRef<Recording>(emptyRecording(null))
    const eventsRef = useRef<string[]>([])
    const historyRef = useRef<ShortRun[]>([])
    const sweepRef = useRef<Sweep | null>(null)
    const redrawQueuedRef = useRef(false)

    const [connected, setConnected] = useState(false)
    const [status, setStatus] = useState<ClusterStatus>({ bornDeadOrParticipating: 0, compileFailed: false, busy: false })
    const [catalog, setCatalog] = useState<Catalog | null>(null)
    const [, setRedraws] = useState(0)

    useEffect(() => {
        connectToRelay()
        return () => disconnectFromRelay()
    }, [])

    function redraw() {
        if (redrawQueuedRef.current) return
        redrawQueuedRef.current = true
        requestAnimationFrame(() => {
            redrawQueuedRef.current = false
            setRedraws(count => count + 1)
        })
    }

    function connectToRelay() {
        cancelledRef.current = false
        const ws = new WebSocket(RELAY_URL)
        wsRef.current = ws

        ws.onopen = () => {
            backoffRef.current = INITIAL_BACKOFF_MS
            setConnected(true)
            ws.send(JSON.stringify({ to: "relay", msg: "i am browser" }))
        }

        ws.onmessage = (event) => {
            const update = JSON.parse(event.data)

            setStatus(old => {
                const next = {
                    bornDeadOrParticipating: update.born_dead_or_participating,
                    compileFailed: update.compile_failed,
                    busy: update.busy,
                }
                const same = old.bornDeadOrParticipating === next.bornDeadOrParticipating
                    && old.compileFailed === next.compileFailed && old.busy === next.busy
                return same ? old : next
            })

            if (update.event) eventsRef.current.push(update.event)
            if (update.catalog) setCatalog(update.catalog)
            if (update.history) historyRef.current = update.history
            if (update.sweep) sweepRef.current = update.sweep
            if (update.run) recordingRef.current = emptyRecording(update.run)
            if (update.frame) addFrame(recordingRef.current, update.frame)
            if (update.summary) {
                // the summary's faults carry the timings that were worked out after the run
                recordingRef.current.summary = update.summary
                recordingRef.current.faults = update.summary.faults
                if (!historyRef.current.some(run => run.id === update.summary.short.id))
                    historyRef.current.push(update.summary.short)
            }
            redraw()
        }

        // relay isn't up yet or went away: retry with backoff
        ws.onclose = () => {
            if (wsRef.current !== ws) return // stale socket from strict mode's double mount
            setConnected(false)
            if (cancelledRef.current) return
            retryTimerRef.current = setTimeout(connectToRelay, backoffRef.current)
            backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS)
        }
    }

    function disconnectFromRelay() {
        cancelledRef.current = true
        if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
        wsRef.current?.close()
    }

    function sendMsg(data: unknown) {
        wsRef.current?.send(JSON.stringify(data))
    }

    // a run that was downloaded earlier, so it can be looked at again without the cluster
    function openSavedRun(saved: { run: RunHeader, frames: Frame[], summary: Summary | null }) {
        const recording = emptyRecording(saved.run)
        for (const frame of saved.frames) addFrame(recording, frame)
        recording.summary = saved.summary
        if (saved.summary) recording.faults = saved.summary.faults
        recordingRef.current = recording
        redraw()
    }

    return {
        connected, status, catalog, sendMsg, openSavedRun,
        recording: recordingRef.current,
        events: eventsRef.current,
        history: historyRef.current,
        sweep: sweepRef.current,
    }
}
