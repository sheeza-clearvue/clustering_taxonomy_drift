import { useRef, useEffect, useState, useCallback, lazy, Suspense } from 'react'
import * as THREE from 'three'

// Dynamic import of the heavy 3D library
let _FG3D = null
function useFG3D() {
  const [loaded, setLoaded] = useState(!!_FG3D)
  useEffect(() => {
    if (_FG3D) return
    import('react-force-graph-3d')
      .then(m => { _FG3D = m.default; setLoaded(true) })
      .catch(err => console.error('Failed to load ForceGraph3D:', err))
  }, [])
  return loaded ? _FG3D : null
}

function nodeObject(node) {
  const radius   = Math.max(2, Math.sqrt(node.cluster_size || 1) * 0.85)
  const isAnom   = node.is_anomaly
  const geo      = new THREE.SphereGeometry(radius, 12, 12)
  const mat      = new THREE.MeshLambertMaterial({
    color:            isAnom ? '#f44747' : node.color || '#569cd6',
    emissive:         isAnom ? '#ff2222' : '#000000',
    emissiveIntensity: isAnom ? 0.45 : 0,
    transparent: true,
    opacity: 0.88,
  })
  return new THREE.Mesh(geo, mat)
}

export default function SemanticGraph3D({
  graphData,
  onNodeClick,
  highlightIds,
  width,
  height,
}) {
  const FG3D   = useFG3D()
  const fgRef  = useRef(null)

  const handleNodeClick = useCallback((node) => {
    onNodeClick?.(node)
    if (fgRef.current) {
      const dist = 80
      const { x = 0, y = 0, z = 0 } = node
      fgRef.current.cameraPosition(
        { x: x + dist, y: y + dist, z: z + dist },
        node,
        800
      )
    }
  }, [onNodeClick])

  const getNodeObject = useCallback((node) => {
    const sphere = nodeObject(node)
    if (highlightIds?.has(node.id)) {
      sphere.material.emissive.set('#ffffff')
      sphere.material.emissiveIntensity = 0.3
    }
    return sphere
  }, [highlightIds])

  const getLinkColor = useCallback(() => 'rgba(255,255,255,0.12)', [])

  useEffect(() => {
    if (fgRef.current) {
      // Pull in the camera slightly from initial position
      setTimeout(() => {
        fgRef.current?.cameraPosition({ z: 450 })
      }, 600)
    }
  }, [graphData])

  if (!FG3D) {
    return (
      <div className="graph-loading">
        <div className="graph-loading-spinner" />
        <span>Initialising 3D engine…</span>
      </div>
    )
  }

  const data = graphData || { nodes: [], links: [] }

  return (
    <FG3D
      ref={fgRef}
      width={width}
      height={height}
      graphData={data}
      nodeLabel={n => `<div class="graph-tooltip-inner"><strong>${n.field_name}</strong><br/>${n.label}<br/><span class="gti-size">size ${n.cluster_size}</span></div>`}
      nodeThreeObject={getNodeObject}
      nodeThreeObjectExtend={false}
      linkColor={getLinkColor}
      linkOpacity={0.5}
      linkWidth={0.4}
      backgroundColor="#1e1e1e"
      onNodeClick={handleNodeClick}
      enableNodeDrag={false}
      showNavInfo={false}
      cooldownTicks={120}
    />
  )
}
