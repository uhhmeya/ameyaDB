import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { Catalog, ClusterStatus } from '../hooks/useRelay.tsx'
import { NUM_NODES } from '../hooks/useRelay.tsx'
import Header from '../header.tsx'

type RunProps = {
    connected: boolean
    sendMsg: (data: unknown) => void
    status: ClusterStatus
    catalog: Catalog | null
}

const MODES = [
    { mode: 'chaos', name: 'random chaos', about: 'crashes, cut links, slow links, lost msgs, slow disks and frozen processes, at random moments and on top of each other' },
    { mode: 'scenario', name: 'handmade edge case', about: 'one situation built by hand that random chaos almost never lands on' },
    { mode: 'sweep', name: 'sweep', about: 'the same test many times with one knob turned a bit further each run' },
]

function Run({ connected, sendMsg, status, catalog }: RunProps) {
    const navigate = useNavigate()
    const ready = status.bornDeadOrParticipating >= NUM_NODES

    const [mode, setMode] = useState('chaos')
    const [scenario, setScenario] = useState('')
    const [sweep, setSweep] = useState('')
    const [seconds, setSeconds] = useState('60')
    const [repeats, setRepeats] = useState('1')
    const [hard, setHard] = useState(true)
    const [prevote, setPrevote] = useState(false)
    const [checkquorum, setCheckquorum] = useState(false)
    const [moreFlags, setMoreFlags] = useState('')
    const [label, setLabel] = useState('')

    useEffect(() => {
        if (!connected) navigate('/')
    }, [connected])

    const picked = mode === 'scenario'
        ? catalog?.scenarios.find(entry => entry.name === scenario) ?? catalog?.scenarios[0]
        : mode === 'sweep' ? catalog?.sweeps.find(entry => entry.name === sweep) ?? catalog?.sweeps[0] : undefined

    function pickMode(next: string) {
        setMode(next)
        setHard(next !== 'sweep')
        if (next === 'chaos') setSeconds('60')
        if (next === 'scenario') setSeconds(String(catalog?.scenarios.find(entry => entry.name === scenario)?.seconds ?? catalog?.scenarios[0]?.seconds ?? 30))
        if (next === 'sweep') setSeconds('40')
    }

    function pickScenario(name: string) {
        setScenario(name)
        setSeconds(String(catalog?.scenarios.find(entry => entry.name === name)?.seconds ?? 30))
    }

    const flags: Record<string, number> = {}
    if (prevote) flags.prevote = 1
    if (checkquorum) flags.checkquorum = 1
    for (const pair of moreFlags.split(/[\s,]+/)) {
        const [name, value] = pair.split('=')
        if (name && value && !Number.isNaN(Number(value))) flags[name] = Number(value)
    }
    const variant = Object.keys(flags).sort().map(name => flags[name] === 1 ? name : `${name}=${flags[name]}`).join('+') || 'baseline'

    function runTest() {
        sendMsg({
            to: "relay", msg: "run",
            config: {
                mode, name: picked?.name ?? '', seconds: Number(seconds) || 60, seed: null,
                hard, flags, label, repeats: Number(repeats) || 1,
            },
        })
        navigate('/debug')
    }

    let content
    if (status.busy) {
        content = (
            <>
                <p className="hint">a test is running</p>
                <Link className="run-button" to="/debug">watch it</Link>
            </>
        )
    } else if (ready) {
        content = (
            <div className="run-form">
                <div className="choices">
                    {MODES.map(option => (
                        <button key={option.mode} className={mode === option.mode ? 'choice picked' : 'choice'} onClick={() => pickMode(option.mode)}>
                            {option.name}
                        </button>
                    ))}
                </div>
                <p className="run-about">{picked?.about ?? MODES.find(option => option.mode === mode)?.about}</p>

                <div className="fields">
                    {mode === 'scenario' && (
                        <label className="field">which one
                            <select value={picked?.name ?? ''} onChange={event => pickScenario(event.target.value)}>
                                {catalog?.scenarios.map(entry => <option key={entry.name}>{entry.name}</option>)}
                            </select>
                        </label>
                    )}
                    {mode === 'sweep' && (
                        <label className="field">which knob
                            <select value={picked?.name ?? ''} onChange={event => setSweep(event.target.value)}>
                                {catalog?.sweeps.map(entry => <option key={entry.name}>{entry.name}</option>)}
                            </select>
                        </label>
                    )}
                    <label className="field">{mode === 'sweep' ? 'seconds per run' : 'seconds of faults'}
                        <input type="number" min="5" value={seconds} onChange={event => setSeconds(event.target.value)} />
                    </label>
                    {mode === 'sweep' && (
                        <label className="field">runs per point
                            <input type="number" min="1" value={repeats} onChange={event => setRepeats(event.target.value)} />
                        </label>
                    )}
                    <label className="field">cut links
                        <select value={hard ? 'firewall' : 'node'} onChange={event => setHard(event.target.value === 'firewall')}>
                            <option value="firewall">with the firewall</option>
                            <option value="node">inside the nodes</option>
                        </select>
                    </label>
                </div>

                <div className="fields">
                    <div className="field wide">switches
                        <div className="switches">
                            <label className="toggle"><input type="checkbox" checked={prevote} onChange={event => setPrevote(event.target.checked)} /> prevote</label>
                            <label className="toggle"><input type="checkbox" checked={checkquorum} onChange={event => setCheckquorum(event.target.checked)} /> checkquorum</label>
                        </div>
                    </div>
                    <label className="field">more flags
                        <input type="text" placeholder="sticky_ms=150" value={moreFlags} onChange={event => setMoreFlags(event.target.value)} />
                    </label>
                    <label className="field">call this variant
                        <input type="text" placeholder={variant} value={label} onChange={event => setLabel(event.target.value)} />
                    </label>
                </div>

                <button className="run-button" onClick={runTest}>run test.py</button>
            </div>
        )
    } else if (status.compileFailed) {
        content = <p className="hint problem">nodes failed to compile</p>
    } else {
        content = (
            <>
                <p className="hint">waiting for all nodes to be born dead ({status.bornDeadOrParticipating}/{NUM_NODES})</p>
                <div className="node-dots" aria-hidden="true">
                    {Array.from({ length: NUM_NODES }, (_, node) => <span key={node} className={node < status.bornDeadOrParticipating ? 'born' : ''} />)}
                </div>
            </>
        )
    }

    return (
        <div className="screen">
            <Header />
            <main className="stage">{content}</main>
        </div>
    )
}

export default Run
