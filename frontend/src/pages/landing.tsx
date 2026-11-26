import { useEffect } from 'react'
import type { ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Frame, RunHeader, Summary } from '../hooks/useRelay.tsx'

type LandingProps = {
    connected: boolean
    openSavedRun: (saved: { run: RunHeader, frames: Frame[], summary: Summary | null }) => void
}

function Landing({ connected, openSavedRun }: LandingProps) {
    const navigate = useNavigate()

    useEffect(() => {
        if (connected) navigate('/run')
    }, [connected])

    async function onFile(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0]
        if (!file) return
        openSavedRun(JSON.parse(await file.text()))
        navigate('/debug')
    }

    return (
        <div className="screen">
            <main className="stage">
                <div className="instructions">
                    <p className="command">
                        <span className="prompt">ameyaDB %</span>
                        <span> chmod +x dooby.sh && ./dooby.sh </span>
                    </p>
                    <p className="hint">Run this to visualize</p>
                    <label className="ghost-button open-saved">
                        or open a run you downloaded
                        <input type="file" accept=".json,application/json" onChange={onFile} />
                    </label>
                </div>
            </main>
        </div>
    )
}

export default Landing
