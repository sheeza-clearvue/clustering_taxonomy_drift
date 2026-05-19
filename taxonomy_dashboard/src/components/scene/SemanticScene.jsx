import { Suspense, useEffect, useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars, Grid } from '@react-three/drei'
import * as THREE from 'three'
import useStore from '../../store/useStore.js'
import ClusterCloud from './ClusterCloud.jsx'
import SceneAxes from './SceneAxes.jsx'
import AmbientParticles from './AmbientParticles.jsx'
import { buildSpatialLayout } from './sceneUtils.js'

// Slow-breathing nebula fog shell — wraps the whole semantic universe
function NebulaFog() {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (!ref.current) return
    ref.current.material.opacity = 0.035 + Math.sin(clock.getElapsedTime() * 0.22) * 0.012
  })
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[260, 32, 32]} />
      <meshBasicMaterial
        color="#040b1a"
        transparent
        opacity={0.04}
        side={THREE.BackSide}
        depthWrite={false}
      />
    </mesh>
  )
}

function SceneContent({ clusters, selectedId, hoveredId, onHover, onClick, showLabels, renderMode }) {
  const cameraReset = useStore(s => s.cameraReset)
  const controlRef  = useRef()

  useEffect(() => {
    if (controlRef.current) {
      controlRef.current.target.set(0, 0, 0)
      controlRef.current.object.position.set(0, 55, 130)
      controlRef.current.update()
    }
  }, [cameraReset])

  return (
    <>
      {/* Ambient + directional lighting tuned for the wider semantic universe */}
      <ambientLight intensity={0.12} color="#081020" />
      <pointLight position={[0,   0,   0]}  intensity={2.2} color="#152a50" distance={300} />
      <pointLight position={[80,  30,  0]}  intensity={1.0} color="#00d4ff" distance={200} decay={1.5} />
      <pointLight position={[-80,-20,  0]}  intensity={0.7} color="#7c3aed" distance={200} decay={1.5} />
      <pointLight position={[0,  -40, 100]} intensity={0.5} color="#10b981" distance={180} decay={1.5} />
      <pointLight position={[0,   40,-100]} intensity={0.4} color="#f97316" distance={180} decay={1.5} />

      {/* Deep-space star field */}
      <Stars radius={400} depth={120} count={6000} factor={5} saturation={0.25} fade speed={0.3} />

      {/* Floor grid matching the new scale */}
      <Grid
        position={[0, -40, 0]}
        args={[500, 500]}
        cellSize={20}
        cellThickness={0.2}
        cellColor="#060e1e"
        sectionSize={80}
        sectionThickness={0.5}
        sectionColor="#0b1830"
        infiniteGrid
        fadeDistance={350}
        fadeStrength={2.5}
      />

      <NebulaFog />

      {/* Axes at the semantic core — clusters orbit them at 55–80 unit radius */}
      <SceneAxes length={40} />

      <AmbientParticles count={1200} />

      {clusters.length > 0 && (
        <ClusterCloud
          clusters={clusters}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onHover={onHover}
          onClick={onClick}
          showLabels={showLabels}
          renderMode={renderMode}
        />
      )}

      <OrbitControls
        ref={controlRef}
        enableDamping
        dampingFactor={0.055}
        rotateSpeed={0.45}
        zoomSpeed={0.7}
        minDistance={8}
        maxDistance={420}
        autoRotate
        autoRotateSpeed={0.10}
      />
    </>
  )
}

export default function SemanticScene({ clusters, showLabels, renderMode }) {
  const {
    selectedClusterId,
    hoveredClusterId,
    setHoveredClusterId,
    setSelectedClusterId,
  } = useStore()

  const positioned = useMemo(
    () => clusters?.length ? buildSpatialLayout(clusters) : [],
    [clusters]
  )

  function handleHover(cluster) {
    setHoveredClusterId(cluster ? (cluster.id ?? null) : null)
  }

  // Single authoritative click handler — manages toggle via store
  function handleClick(cluster) {
    if (!cluster) return
    const id = cluster.id ?? null
    setSelectedClusterId(prev => prev === id ? null : id)
  }

  return (
    <Canvas
      camera={{ position: [0, 55, 130], fov: 62, near: 0.5, far: 800 }}
      gl={{
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
        toneMapping: THREE.ACESFilmicToneMapping,
        toneMappingExposure: 1.15,
      }}
      style={{ background: 'radial-gradient(ellipse at 50% 40%, #030c1a 0%, #02050a 100%)' }}
    >
      <Suspense fallback={null}>
        <SceneContent
          clusters={positioned}
          selectedId={selectedClusterId}
          hoveredId={hoveredClusterId}
          onHover={handleHover}
          onClick={handleClick}
          showLabels={showLabels}
          renderMode={renderMode}
        />
      </Suspense>
    </Canvas>
  )
}
