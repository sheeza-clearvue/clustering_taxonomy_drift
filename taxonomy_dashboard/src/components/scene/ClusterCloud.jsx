import { useRef, useMemo, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'

// ─ Pulsing anomaly torus ───────────────────────────────────────────────────────
function AnomalyRing({ position, color, size }) {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.getElapsedTime()
    ref.current.scale.setScalar(1 + Math.sin(t * 2.0) * 0.3)
    ref.current.material.opacity = 0.28 - Math.sin(t * 2.0) * 0.15
  })
  return (
    <mesh ref={ref} position={position}>
      <torusGeometry args={[size * 4.2, 0.07, 8, 32]} />
      <meshBasicMaterial color={color} transparent opacity={0.25} depthWrite={false} />
    </mesh>
  )
}

// ─ Floating cluster label ──────────────────────────────────────────────────────
function ClusterLabel({ cluster }) {
  const name = cluster.display_name || (cluster.cluster_id ? String(cluster.cluster_id).slice(-10) : '')
  if (!name) return null
  const yOff = cluster._size * 5.5 + 2
  return (
    <Html
      position={[cluster._pos[0], cluster._pos[1] + yOff, cluster._pos[2]]}
      center
      style={{ pointerEvents: 'none' }}
    >
      <div style={{
        color: cluster._color,
        fontSize: '9px',
        fontFamily: '"Cascadia Code","Fira Code",monospace',
        fontWeight: 700,
        letterSpacing: '0.06em',
        textShadow: `0 0 8px ${cluster._color}, 0 0 20px ${cluster._color}55`,
        userSelect: 'none',
        whiteSpace: 'nowrap',
        padding: '2px 8px',
        borderRadius: 4,
        background: 'rgba(2,5,10,0.72)',
        border: `1px solid ${cluster._color}28`,
        backdropFilter: 'blur(8px)',
      }}>
        {name.length > 28 ? name.slice(0, 28) + '…' : name}
      </div>
    </Html>
  )
}

// ─ Hover tooltip ──────────────────────────────────────────────────────────────
function ClusterTooltip({ cluster }) {
  const yOff = cluster._size * 5.5 + 4
  return (
    <Html
      position={[cluster._pos[0], cluster._pos[1] + yOff, cluster._pos[2]]}
      style={{ pointerEvents: 'none' }}
    >
      <div style={{
        transform: 'translate(-50%, -6px)',
        background: 'rgba(3,8,15,0.97)',
        border: `1px solid ${cluster._color}44`,
        borderRadius: 9,
        padding: '10px 14px',
        minWidth: 190,
        maxWidth: 250,
        backdropFilter: 'blur(24px)',
        boxShadow: `0 10px 40px rgba(0,0,0,0.85), 0 0 28px ${cluster._color}12`,
        fontFamily: 'Inter, system-ui, sans-serif',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 8,
            background: cluster._color + '22', color: cluster._color,
            border: `1px solid ${cluster._color}40`,
          }}>
            {cluster.field_name}
          </span>
          {cluster.is_true_anomaly_cluster && (
            <span style={{
              fontSize: 9, padding: '2px 7px', borderRadius: 8,
              background: 'rgba(255,51,68,0.2)', color: '#ff3344', fontWeight: 700,
            }}>
              ANOMALY
            </span>
          )}
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 5, lineHeight: 1.35 }}>
          {cluster.display_name || cluster.cluster_id || 'Unnamed Cluster'}
        </div>
        {cluster.medoid_label && (
          <div style={{ fontSize: 10, color: '#64748b', fontStyle: 'italic', marginBottom: 6, lineHeight: 1.4 }}>
            "{cluster.medoid_label.length > 55 ? cluster.medoid_label.slice(0, 55) + '…' : cluster.medoid_label}"
          </div>
        )}
        <div style={{ display: 'flex', gap: 14, fontSize: 10.5, color: '#475569' }}>
          <span><span style={{ color: '#94a3b8' }}>{(cluster.cluster_size || 0).toLocaleString()}</span> items</span>
          <span><span style={{ color: '#94a3b8' }}>{cluster.label_count || 0}</span> labels</span>
        </div>
      </div>
    </Html>
  )
}

// ─ Nearest-neighbor link lines (shown on hover/select) ────────────────────────
function NeighborLinks({ focus, neighbors }) {
  const matRef = useRef()

  const geo = useMemo(() => {
    const pts = []
    neighbors.forEach(n => { pts.push(...focus._pos, ...n._pos) })
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pts), 3))
    return g
  }, [focus, neighbors])

  useFrame(({ clock }) => {
    if (matRef.current) {
      matRef.current.opacity = 0.10 + Math.sin(clock.getElapsedTime() * 2.8) * 0.07
    }
  })

  return (
    <lineSegments geometry={geo}>
      <lineBasicMaterial
        ref={matRef}
        color={focus._color}
        transparent
        opacity={0.12}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </lineSegments>
  )
}

// ─ Main ClusterCloud ───────────────────────────────────────────────────────────
export default function ClusterCloud({
  clusters,
  selectedId,
  hoveredId,
  onHover,
  onClick,
  showLabels,
  renderMode,
}) {
  const coreRef = useRef()
  const haloRef = useRef()
  const N = clusters.length

  const sphereGeo = useMemo(() => new THREE.SphereGeometry(1, 10, 10), [])

  // ── Two-layer nebula particle system ────────────────────────────────────────
  const { hazeGeo, innerGeo } = useMemo(() => {
    const hazePos = [], hazeCol = []
    const innerPos = [], innerCol = []
    const color = new THREE.Color()

    clusters.forEach(c => {
      const sizeLog = Math.log(Math.max(c.cluster_size || 1, 1) + 1)
      const spread  = Math.max(c._size * 7.5, 3.0)
      color.set(c._color)

      // Outer haze — wide spread, very translucent
      const nHaze = Math.min(Math.floor(sizeLog * 20 + 14), 140)
      for (let i = 0; i < nHaze; i++) {
        const r     = spread * (0.38 + Math.random() * 0.62)
        const theta = Math.random() * Math.PI * 2
        const phi   = Math.acos(2 * Math.random() - 1)
        hazePos.push(
          c._pos[0] + r * Math.sin(phi) * Math.cos(theta),
          c._pos[1] + r * Math.cos(phi) * 0.5,
          c._pos[2] + r * Math.sin(phi) * Math.sin(theta),
        )
        hazeCol.push(color.r, color.g, color.b)
      }

      // Inner core — tight, dense, bright
      const nInner = Math.min(Math.floor(sizeLog * 12 + 10), 90)
      for (let i = 0; i < nInner; i++) {
        const r     = spread * Math.random() * 0.36
        const theta = Math.random() * Math.PI * 2
        const phi   = Math.acos(2 * Math.random() - 1)
        innerPos.push(
          c._pos[0] + r * Math.sin(phi) * Math.cos(theta),
          c._pos[1] + r * Math.cos(phi) * 0.48,
          c._pos[2] + r * Math.sin(phi) * Math.sin(theta),
        )
        innerCol.push(color.r, color.g, color.b)
      }
    })

    function buildGeo(pos, col) {
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3))
      g.setAttribute('color',    new THREE.BufferAttribute(new Float32Array(col), 3))
      return g
    }

    return { hazeGeo: buildGeo(hazePos, hazeCol), innerGeo: buildGeo(innerPos, innerCol) }
  }, [clusters])

  // ── Centroid instanced mesh updates ─────────────────────────────────────────
  useEffect(() => {
    if (!coreRef.current || !haloRef.current) return
    const mat = new THREE.Matrix4()
    const color = new THREE.Color()

    for (let i = 0; i < N; i++) {
      const cl  = clusters[i]
      const sel = selectedId === cl.id
      const hov = hoveredId  === cl.id
      const s   = cl._size * 1.35 * (sel ? 2.8 : hov ? 2.1 : 1)
      const gs  = s * 3.8

      mat.compose(new THREE.Vector3(...cl._pos), new THREE.Quaternion(), new THREE.Vector3(s, s, s))
      coreRef.current.setMatrixAt(i, mat)
      mat.compose(new THREE.Vector3(...cl._pos), new THREE.Quaternion(), new THREE.Vector3(gs, gs, gs))
      haloRef.current.setMatrixAt(i, mat)

      color.set(sel || hov ? '#ffffff' : cl._color)
      coreRef.current.setColorAt(i, color)
      color.set(cl._color)
      haloRef.current.setColorAt(i, color)
    }

    coreRef.current.instanceMatrix.needsUpdate = true
    if (coreRef.current.instanceColor) coreRef.current.instanceColor.needsUpdate = true
    haloRef.current.instanceMatrix.needsUpdate  = true
    if (haloRef.current.instanceColor) haloRef.current.instanceColor.needsUpdate = true
  }, [clusters, selectedId, hoveredId, N])

  // Breathing glow — halo opacity pulses slowly over time
  useFrame(({ clock }) => {
    if (haloRef.current?.material) {
      const t = clock.getElapsedTime()
      haloRef.current.material.opacity = 0.032 + Math.sin(t * 0.7) * 0.016
    }
  })

  // ── Nearest-neighbor computation (hover + selected) ──────────────────────────
  const { focusCluster, nearestNeighbors } = useMemo(() => {
    const focusId = hoveredId ?? selectedId
    if (focusId == null || !clusters.length) return { focusCluster: null, nearestNeighbors: [] }
    const focus = clusters.find(c => c.id === focusId)
    if (!focus) return { focusCluster: null, nearestNeighbors: [] }

    const [fx, fy, fz] = focus._pos
    const nearest = clusters
      .filter(c => c.id !== focusId)
      .map(c => {
        const dx = c._pos[0] - fx, dy = c._pos[1] - fy, dz = c._pos[2] - fz
        return { c, d2: dx * dx + dy * dy + dz * dz }
      })
      .sort((a, b) => a.d2 - b.d2)
      .slice(0, 6)
      .map(({ c }) => c)

    return { focusCluster: focus, nearestNeighbors: nearest }
  }, [hoveredId, selectedId, clusters])

  const hoveredCluster = hoveredId != null ? clusters.find(c => c.id === hoveredId) : null

  const labelClusters = (showLabels || renderMode === 'labels')
    ? clusters.filter(c => c._size > 0.22 || (c.cluster_size || 0) > 4).slice(0, 60)
    : []

  const isDensity   = renderMode === 'density'
  const hazeOpacity = isDensity ? 0.16 : 0.09
  const innerOp     = isDensity ? 0.55 : 0.35
  const hazeSize    = isDensity ? 0.28 : 0.18
  const innerSize   = isDensity ? 0.14 : 0.088

  return (
    <group>
      {/* ─ Outer nebula haze — NON-INTERACTIVE (raycast disabled) ─ */}
      <points geometry={hazeGeo} raycast={() => {}}>
        <pointsMaterial
          vertexColors size={hazeSize} transparent opacity={hazeOpacity}
          sizeAttenuation depthWrite={false} blending={THREE.AdditiveBlending}
        />
      </points>

      {/* ─ Inner dense core particles — NON-INTERACTIVE ─ */}
      <points geometry={innerGeo} raycast={() => {}}>
        <pointsMaterial
          vertexColors size={innerSize} transparent opacity={innerOp}
          sizeAttenuation depthWrite={false} blending={THREE.AdditiveBlending}
        />
      </points>

      {/* ─ Halo glow spheres — NON-INTERACTIVE (breathing via useFrame) ─ */}
      <instancedMesh ref={haloRef} args={[sphereGeo, null, N]} raycast={() => {}}>
        <meshBasicMaterial
          transparent opacity={0.038} depthWrite={false}
          blending={THREE.AdditiveBlending} vertexColors
        />
      </instancedMesh>

      {/* ─ Centroid core spheres — ONLY interactive geometry ─ */}
      <instancedMesh
        ref={coreRef}
        args={[sphereGeo, null, N]}
        onClick={e => {
          e.stopPropagation()
          const i = e.instanceId
          if (i != null) onClick(clusters[i])
        }}
        onPointerMove={e => {
          e.stopPropagation()
          const i = e.instanceId
          if (i != null) onHover(clusters[i])
        }}
        onPointerLeave={() => onHover(null)}
      >
        <meshStandardMaterial
          vertexColors
          roughness={0.06}
          metalness={0.65}
          emissive="#ffffff"
          emissiveIntensity={0.05}
        />
      </instancedMesh>

      {/* ─ Semantic neighbor links (hover / select) ─ */}
      {focusCluster && nearestNeighbors.length > 0 && (
        <NeighborLinks focus={focusCluster} neighbors={nearestNeighbors} />
      )}

      {/* ─ Anomaly pulse rings ─ */}
      {clusters
        .filter(c => c.is_true_anomaly_cluster)
        .slice(0, 50)
        .map((c, i) => (
          <AnomalyRing key={c.id ?? i} position={c._pos} color={c._color} size={c._size} />
        ))
      }

      {/* ─ Floating labels ─ */}
      {labelClusters.map(c => (
        <ClusterLabel key={c.id} cluster={c} />
      ))}

      {/* ─ Hover tooltip ─ */}
      {hoveredCluster && <ClusterTooltip cluster={hoveredCluster} />}
    </group>
  )
}
