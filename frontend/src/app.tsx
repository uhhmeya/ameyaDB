import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useRelay } from './utils/useRelay.tsx'
import Landing from './landing'
import Run from './run'

function App() {
    const { connected, send_msg } = useRelay()

    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Landing connected={connected} />} />
                <Route path="/run" element={<Run connected={connected} send_msg={send_msg} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App