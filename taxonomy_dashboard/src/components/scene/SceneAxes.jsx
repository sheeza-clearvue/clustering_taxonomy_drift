import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'

// Animated glow line — core + halo pass
function GlowLine({ from, to, color }) {
  const hazeRef = useRef()
  const points = [new THREE.Vector3(...from), new THREE.Vector3(...to)]
  const geo    = new THREE.BufferGeometry().setFromPoints(points)

  useFrame(({ clock }) => {
    if (hazeRef.current) {
      hazeRef.current.material.opacity = 0.08 + Math.sin(clock.getElapsedTime() * 0.6) * 0.04
    }
  })

  return (
    <group>
      {/* Core line */}
      <line geometry={geo}>
        <lineBasicMaterial color={color} transparent opacity={0.65} />
      </line>
      {/* Animated glow halo */}
      <line ref={hazeRef} geometry={geo}>
        <lineBasicMaterial color={color} transparent opacity={0.10} linewidth={3} />
      </line>
    </group>
  )
}

function AxisLabel({ position, label, color }) {
  return (
    <Html position={position} center>
      <div style={{
        color,
        fontSize: '9px',
        fontFamily: '"Cascadia Code","Fira Code",monospace',
        fontWeight: 700,
        letterSpacing: '0.09em',
        textShadow: `0 0 10px ${color}, 0 0 24px ${color}55`,
        userSelect: 'none',
        pointerEvents: 'none',
        whiteSpace: 'nowrap',
        opacity: 0.85,
        padding: '2px 6px',
        borderRadius: 4,
        background: 'rgba(2,5,10,0.5)',
        border: `1px solid ${color}22`,
        backdropFilter: 'blur(4px)',
      }}>
        {label}
      </div>
    </Html>
  )
}

// Pulsing origin core
function OriginCore() {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.getElapsedTime()
    ref.current.material.opacity = 0.5 + Math.sin(t * 1.2) * 0.25
    const s = 1 + Math.sin(t * 1.2) * 0.15
    ref.current.scale.setScalar(s)
  })
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.35, 16, 16]} />
      <meshBasicMaterial color="#ffffff" transparent opacity={0.6} />
    </mesh>
  )
}

export default function SceneAxes({ length = 40 }) {
  return (
    <group>
      {/* X — Semantic Polarity */}
      <GlowLine from={[-length, 0, 0]} to={[length, 0, 0]} color="#00d4ff" />
      <AxisLabel position={[length + 3, 0.5, 0]} label="Semantic Polarity →" color="#00d4ff" />

      {/* Y — Operational Intent */}
      <GlowLine from={[0, -length * 0.6, 0]} to={[0, length * 0.6, 0]} color="#a855f7" />
      <AxisLabel position={[0.5, length * 0.6 + 2, 0]} label="↑ Operational Intent" color="#a855f7" />

      {/* Z — Confidence / Density */}
      <GlowLine from={[0, 0, -length]} to={[0, 0, length]} color="#10b981" />
      <AxisLabel position={[0, 0.5, length + 3]} label="Confidence / Density →" color="#10b981" />

      <OriginCore />
    </group>
  )
}
