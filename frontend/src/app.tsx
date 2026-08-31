import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useRelay } from './hooks/useRelay.tsx'
import { useCluster } from './hooks/useCluster.tsx'
import Landing from './pages/landing.tsx'
import Run from './pages/run.tsx'
import Debug from './pages/debug.tsx'

function App() {
    const { cluster, hellos, ingest } = useCluster()
    const { connected, log, send_msg } = useRelay(ingest)

    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Landing connected={connected} />} />
                <Route path="/run" element={<Run connected={connected}
                                                 send_msg={send_msg}
                                                 hellos={hellos} />} />
                <Route path="/debug" element={<Debug cluster={cluster} log={log} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App