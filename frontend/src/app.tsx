import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useRelay } from './hooks/useRelay.tsx'
import Landing from './pages/landing.tsx'
import Run from './pages/run.tsx'
import Debug from './pages/debug.tsx'

function App() {
    const { connected, log, sendMsg } = useRelay()

    // every update carries the whole cluster status, so the newest one is current
    const latest = log.at(-1)

    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Landing connected={connected} />} />
                <Route path="/run" element={
                    <Run connected={connected}
                         sendMsg={sendMsg}
                         bornDeadOrParticipating={latest?.born_dead_or_participating ?? 0}
                         compileFailed={latest?.compile_failed ?? false} />
                } />
                <Route path="/debug" element={<Debug log={log} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App
