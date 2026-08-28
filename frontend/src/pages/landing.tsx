import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

type LandingProps = {
    connected: boolean
}

function Landing({ connected }: LandingProps) {
    const navigate = useNavigate()

    // once relay connects, go to the run screen
    useEffect(() => {
        if (connected) navigate('/run')
    }, [connected])

    return (
        <div className="fullscreen">
            <div className="instructions">
                <p className="command">
                    <span className="prompt">ameyaDB %</span>
                    <span> chmod +x dooby.sh && ./dooby.sh </span>
                </p>
                <p className="hint">Run this to visualize</p>
            </div>
        </div>
    )
}

export default Landing