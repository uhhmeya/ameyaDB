import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

type RunProps = {
    connected: boolean
    send_msg: (data: unknown) => void
}

function Run({ connected, send_msg }: RunProps) {
    const navigate = useNavigate()

    // if relay crashes, go back to the landing screen
    useEffect(() => {
        if (!connected) navigate('/')
    }, [connected])

    return (
        <div className="fullscreen">
            <button className="run-button" onClick={() =>
                // sends this to relay
                send_msg({msg:"run_test.py"})}>
                run test.py
            </button>
        </div>
    )
}

export default Run