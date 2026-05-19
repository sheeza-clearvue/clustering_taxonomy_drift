import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

export default function AmbientParticles({ count = 1200 }) {
  const meshRef = useRef()

  const { positions, velocities } = useMemo(() => {
    const positions  = new Float32Array(count * 3)
    const velocities = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      // Scatter across a much wider volume to match the new cluster spread
      const r     = 80 + Math.random() * 120
      const theta = Math.random() * Math.PI * 2
      const phi   = Math.acos(2 * Math.random() - 1)
      positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = r * Math.cos(phi)
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
      velocities[i * 3]     = (Math.random() - 0.5) * 0.006
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.004
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.006
    }
    return { positions, velocities }
  }, [count])

  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions.slice(), 3))
    return g
  }, [positions])

  useFrame((_, delta) => {
    if (!meshRef.current) return
    const pos = meshRef.current.geometry.attributes.position.array
    for (let i = 0; i < count; i++) {
      pos[i * 3]     += velocities[i * 3]
      pos[i * 3 + 1] += velocities[i * 3 + 1]
      pos[i * 3 + 2] += velocities[i * 3 + 2]
      const d = Math.sqrt(pos[i*3]**2 + pos[i*3+1]**2 + pos[i*3+2]**2)
      if (d > 220) {
        pos[i * 3]     *= 0.996
        pos[i * 3 + 1] *= 0.996
        pos[i * 3 + 2] *= 0.996
      }
    }
    meshRef.current.geometry.attributes.position.needsUpdate = true
  })

  return (
    <points ref={meshRef} geometry={geo} raycast={() => {}}>
      <pointsMaterial
        color="#3a5a88"
        size={0.12}
        transparent
        opacity={0.30}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  )
}
