import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useRelay } from './utils/useRelay.tsx'
import Landing from './pages/landing.tsx'
import Run from './pages/run.tsx'
import Debug from './pages/debug.tsx'

function App() {
    const { connected, messages, roster, ready, send_msg } = useRelay()

    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Landing connected={connected} />} />
                <Route path="/run" element={<Run connected={connected}
                                                 send_msg={send_msg}
                                                 messages={messages}
                                                 roster={roster}
                                                 ready={ready} />} />
                <Route path="/debug" element={<Debug messages={messages} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App