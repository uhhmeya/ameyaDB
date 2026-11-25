import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useRelay } from './hooks/useRelay.tsx'
import Landing from './pages/landing.tsx'
import Run from './pages/run.tsx'
import Debug from './pages/debug.tsx'
import Compare from './pages/compare.tsx'

function App() {
    const { connected, status, catalog, recording, events, history, sweep, sendMsg, openSavedRun } = useRelay()

    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Landing connected={connected} openSavedRun={openSavedRun} />} />
                <Route path="/run" element={<Run connected={connected} sendMsg={sendMsg} status={status} catalog={catalog} />} />
                <Route path="/debug" element={<Debug recording={recording} events={events} status={status} sweep={sweep} sendMsg={sendMsg} />} />
                <Route path="/compare" element={<Compare history={history} sweep={sweep} catalog={catalog} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App
