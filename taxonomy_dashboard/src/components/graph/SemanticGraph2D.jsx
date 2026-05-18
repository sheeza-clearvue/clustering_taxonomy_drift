import { useRef, useEffect, useState, useCallback } from 'react'
import { getFieldColor } from '../../utils/colors.js'

const MIN_SCALE   = 0.08
const MAX_SCALE   = 10
const ZOOM_STEP   = 0.12
const ALPHA_START = 1.0
const ALPHA_DECAY = 0.007

function buildState() {
  return {
    nodes: [], links: [], nodeById: {},
    transform: { x: 0, y: 0, scale: 1 },
    dragNode: null, isPanning: false, panStart: null,
    hoveredNode: null, alpha: ALPHA_START,
    animId: null, showLabels: false,
    particles: [],
  }
}

function initParticles(W, H, n = 60) {
  return Array.from({ length: n }, () => ({
    x: Math.random() * W, y: Math.random() * H,
    vx: (Math.random() - 0.5) * 0.15, vy: (Math.random() - 0.5) * 0.15,
    r: Math.random() * 1.2 + 0.3, a: Math.random() * 0.25 + 0.05,
  }))
}

function tickSim(s, W, H) {
  if (s.alpha <= 0) return false
  s.alpha = Math.max(0, s.alpha - ALPHA_DECAY)
  const a = s.alpha
  const { nodes, links, nodeById } = s

  // Repulsion
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const na = nodes[i], nb = nodes[j]
      let dx = nb.x - na.x, dy = nb.y - na.y
      const d2 = dx * dx + dy * dy || 0.01
      const d  = Math.sqrt(d2)
      const f  = (2400 * a) / d2
      na.vx -= (dx / d) * f; na.vy -= (dy / d) * f
      nb.vx += (dx / d) * f; nb.vy += (dy / d) * f
    }
  }

  // Link springs
  for (const l of links) {
    const s2 = nodeById[l.source?.id ?? l.source]
    const t  = nodeById[l.target?.id ?? l.target]
    if (!s2 || !t) continue
    const dx = t.x - s2.x, dy = t.y - s2.y
    const d  = Math.sqrt(dx * dx + dy * dy) || 1
    const f  = (d - 100) * 0.045 * a
    s2.vx += (dx / d) * f; s2.vy += (dy / d) * f
    t.vx  -= (dx / d) * f; t.vy  -= (dy / d) * f
  }

  const cx = W / 2, cy = H / 2
  for (const n of nodes) {
    if (s.dragNode?.id === n.id) { n.vx = 0; n.vy = 0; continue }
    // Center gravity
    n.vx += (cx - n.x) * 0.0025 * a
    n.vy += (cy - n.y) * 0.0025 * a
    // Anomaly outward push
    if (n.is_anomaly) {
      const dx = n.x - cx, dy = n.y - cy
      const d  = Math.sqrt(dx * dx + dy * dy) || 1
      n.vx += (dx / d) * 3.5 * a
      n.vy += (dy / d) * 3.5 * a
    }
    // Large cluster centrality pull
    if (n.cluster_size > 30) {
      n.vx += (cx - n.x) * 0.001 * a
      n.vy += (cy - n.y) * 0.001 * a
    }
    n.vx *= 0.80; n.vy *= 0.80
    n.x += n.vx;  n.y += n.vy
  }
  return true
}

function drawScene(s, ctx, W, H) {
  ctx.clearRect(0, 0, W, H)

  // Animated background particles
  ctx.save()
  for (const p of s.particles) {
    p.x += p.vx; p.y += p.vy
    if (p.x < 0) p.x = W; if (p.x > W) p.x = 0
    if (p.y < 0) p.y = H; if (p.y > H) p.y = 0
    ctx.beginPath()
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(86,156,214,${p.a})`
    ctx.fill()
  }
  ctx.restore()

  // Dot grid
  ctx.save()
  const { x: tx, y: ty, scale } = s.transform
  const gSize = 36 * scale
  const ox = tx % gSize, oy = ty % gSize
  ctx.fillStyle = 'rgba(255,255,255,0.025)'
  for (let gx = ox; gx < W + gSize; gx += gSize) {
    for (let gy = oy; gy < H + gSize; gy += gSize) {
      ctx.beginPath(); ctx.arc(gx, gy, 0.7, 0, Math.PI * 2); ctx.fill()
    }
  }
  ctx.restore()

  ctx.save()
  ctx.translate(tx, ty)
  ctx.scale(scale, scale)

  // Links
  for (const l of s.links) {
    const src = s.nodeById[l.source?.id ?? l.source]
    const tgt = s.nodeById[l.target?.id ?? l.target]
    if (!src || !tgt) continue
    const gradient = ctx.createLinearGradient(src.x, src.y, tgt.x, tgt.y)
    gradient.addColorStop(0, `${src.color}30`)
    gradient.addColorStop(1, `${tgt.color}30`)
    ctx.beginPath()
    ctx.moveTo(src.x, src.y)
    ctx.lineTo(tgt.x, tgt.y)
    ctx.strokeStyle = gradient
    ctx.lineWidth = 0.8 / scale
    ctx.stroke()
  }

  // Nodes
  for (const n of s.nodes) {
    const r       = Math.max(5, Math.sqrt(n.cluster_size || 1) * 1.4)
    const isHov   = s.hoveredNode?.id === n.id
    const color   = n.is_anomaly ? '#f44747' : n.color
    const glowR   = n.is_anomaly ? (isHov ? 24 : 12) : (isHov ? 16 : 6)
    const glowCol = n.is_anomaly ? '#ff4444' : (isHov ? color : color + '88')

    // Outer glow
    ctx.beginPath()
    ctx.arc(n.x, n.y, r + (isHov ? 8 : 4), 0, Math.PI * 2)
    const grd = ctx.createRadialGradient(n.x, n.y, r * 0.5, n.x, n.y, r + (isHov ? 10 : 5))
    grd.addColorStop(0, color + (n.is_anomaly ? '55' : '33'))
    grd.addColorStop(1, 'transparent')
    ctx.fillStyle = grd
    ctx.fill()

    // Node body
    ctx.beginPath()
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
    ctx.shadowColor = glowCol
    ctx.shadowBlur  = glowR
    const bodyGrd = ctx.createRadialGradient(n.x - r * 0.3, n.y - r * 0.3, 0, n.x, n.y, r)
    bodyGrd.addColorStop(0, lighten(color, 0.3))
    bodyGrd.addColorStop(1, color)
    ctx.fillStyle = bodyGrd
    ctx.globalAlpha = n.is_anomaly ? 0.95 : (isHov ? 1 : 0.88)
    ctx.fill()
    ctx.shadowBlur = 0
    ctx.globalAlpha = 1

    // Hover ring
    if (isHov) {
      ctx.beginPath()
      ctx.arc(n.x, n.y, r + 4, 0, Math.PI * 2)
      ctx.strokeStyle = color + 'cc'
      ctx.lineWidth   = 1.5 / scale
      ctx.stroke()
    }

    // Anomaly pulse ring
    if (n.is_anomaly) {
      const pulse = 0.5 + 0.5 * Math.sin(Date.now() * 0.004)
      ctx.beginPath()
      ctx.arc(n.x, n.y, r + 6 + pulse * 4, 0, Math.PI * 2)
      ctx.strokeStyle = `rgba(244,71,71,${0.2 + pulse * 0.15})`
      ctx.lineWidth   = 1 / scale
      ctx.stroke()
    }

    // Label
    if (s.showLabels || isHov || n.cluster_size > 80) {
      const lbl   = (n.label || n.cluster_id || '').slice(0, 22)
      const fsize = Math.max(9, Math.min(13, 11 / scale))
      ctx.font        = `${fsize}px 'Segoe UI', sans-serif`
      ctx.shadowColor = 'rgba(0,0,0,0.9)'
      ctx.shadowBlur  = 4
      ctx.fillStyle   = isHov ? '#ffffff' : 'rgba(255,255,255,0.75)'
      ctx.globalAlpha = 1
      ctx.fillText(lbl, n.x + r + 5, n.y + fsize * 0.35)
      ctx.shadowBlur = 0
    }
  }

  ctx.restore()
}

function lighten(hex, amount) {
  const n = parseInt(hex.replace('#', ''), 16)
  const r = Math.min(255, ((n >> 16) & 0xff) + Math.round(amount * 255))
  const g = Math.min(255, ((n >>  8) & 0xff) + Math.round(amount * 255))
  const b = Math.min(255, ( n        & 0xff) + Math.round(amount * 255))
  return `rgb(${r},${g},${b})`
}

function toWorld(cx, cy, t) {
  return { wx: (cx - t.x) / t.scale, wy: (cy - t.y) / t.scale }
}

function hitNode(wx, wy, nodes, scale) {
  const slop = 6 / scale
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i]
    const r = Math.max(5, Math.sqrt(n.cluster_size || 1) * 1.4) + slop
    if ((wx - n.x) ** 2 + (wy - n.y) ** 2 <= r * r) return n
  }
  return null
}

export default function SemanticGraph2D({ graphData, onNodeClick, highlightIds, width, height }) {
  const canvasRef  = useRef(null)
  const sRef       = useRef(buildState())
  const [tooltip,  setTooltip] = useState(null)
  const [, forceRender] = useState(0)

  const resetCamera = useCallback(() => {
    sRef.current.transform = { x: 0, y: 0, scale: 1 }
    const c = canvasRef.current
    if (c) drawScene(sRef.current, c.getContext('2d'), c.width, c.height)
  }, [])

  const toggleLabels = useCallback(() => {
    sRef.current.showLabels = !sRef.current.showLabels
    const c = canvasRef.current
    if (c) drawScene(sRef.current, c.getContext('2d'), c.width, c.height)
    forceRender(v => v + 1)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !graphData?.nodes?.length) return

    const W = width  || canvas.offsetWidth  || 900
    const H = height || canvas.offsetHeight || 600
    canvas.width  = W
    canvas.height = H

    const s = sRef.current
    s.nodes = graphData.nodes.map(n => ({
      ...n,
      x: W * 0.15 + Math.random() * W * 0.7,
      y: H * 0.15 + Math.random() * H * 0.7,
      vx: 0, vy: 0,
      color: n.is_anomaly ? '#f44747' : getFieldColor(n.field_name),
    }))
    s.links    = graphData.links || []
    s.nodeById = {}
    for (const n of s.nodes) s.nodeById[n.id] = n
    s.alpha       = ALPHA_START
    s.hoveredNode = null
    s.dragNode    = null
    s.isPanning   = false
    s.particles   = initParticles(W, H)

    const ctx = canvas.getContext('2d')

    let rafId = null
    function loop() {
      const active = tickSim(s, W, H)
      drawScene(s, ctx, W, H)
      if (active || s.dragNode || s.particles.length) {
        rafId = s.animId = requestAnimationFrame(loop)
      } else {
        s.animId = null
      }
    }
    rafId = requestAnimationFrame(loop)

    // Wheel zoom
    function onWheel(e) {
      e.preventDefault()
      const rect   = canvas.getBoundingClientRect()
      const mx     = e.clientX - rect.left
      const my     = e.clientY - rect.top
      const delta  = e.deltaY < 0 ? 1 + ZOOM_STEP : 1 / (1 + ZOOM_STEP)
      const prev   = s.transform.scale
      const next   = Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev * delta))
      s.transform.x = mx - (mx - s.transform.x) * (next / prev)
      s.transform.y = my - (my - s.transform.y) * (next / prev)
      s.transform.scale = next
      drawScene(s, ctx, W, H)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })

    let hoverRaf = null
    function onMouseMove(e) {
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const { wx, wy } = toWorld(mx, my, s.transform)

      if (s.dragNode) {
        s.dragNode.x = wx; s.dragNode.y = wy
        s.dragNode.vx = 0; s.dragNode.vy = 0
        if (!s.animId) { rafId = s.animId = requestAnimationFrame(loop) }
        return
      }

      if (s.isPanning && s.panStart) {
        s.transform.x += mx - s.panStart.mx
        s.transform.y += my - s.panStart.my
        s.panStart = { mx, my }
        drawScene(s, ctx, W, H)
        return
      }

      if (hoverRaf) return
      hoverRaf = requestAnimationFrame(() => {
        hoverRaf = null
        const hit = hitNode(wx, wy, s.nodes, s.transform.scale)
        if (hit !== s.hoveredNode) {
          s.hoveredNode = hit
          canvas.style.cursor = hit ? 'pointer' : 'grab'
          drawScene(s, ctx, W, H)
        }
        setTooltip(hit ? { x: e.clientX, y: e.clientY, node: hit } : null)
      })
    }

    function onMouseDown(e) {
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const { wx, wy } = toWorld(mx, my, s.transform)
      const hit = hitNode(wx, wy, s.nodes, s.transform.scale)
      if (hit) {
        s.dragNode = hit
      } else {
        s.isPanning = true
        s.panStart  = { mx, my }
        canvas.style.cursor = 'grabbing'
      }
    }

    function onMouseUp() {
      s.dragNode  = null
      s.isPanning = false
      s.panStart  = null
      canvas.style.cursor = 'grab'
    }

    function onClick(e) {
      if (s.dragNode || s.isPanning) return
      const rect = canvas.getBoundingClientRect()
      const { wx, wy } = toWorld(e.clientX - rect.left, e.clientY - rect.top, s.transform)
      const hit = hitNode(wx, wy, s.nodes, s.transform.scale)
      if (hit) onNodeClick?.(hit)
    }

    function onLeave() { s.hoveredNode = null; setTooltip(null) }

    canvas.addEventListener('mousemove',  onMouseMove)
    canvas.addEventListener('mousedown',  onMouseDown)
    canvas.addEventListener('mouseup',    onMouseUp)
    canvas.addEventListener('click',      onClick)
    canvas.addEventListener('mouseleave', onLeave)
    canvas.style.cursor = 'grab'

    return () => {
      cancelAnimationFrame(rafId)
      canvas.removeEventListener('wheel',      onWheel)
      canvas.removeEventListener('mousemove',  onMouseMove)
      canvas.removeEventListener('mousedown',  onMouseDown)
      canvas.removeEventListener('mouseup',    onMouseUp)
      canvas.removeEventListener('click',      onClick)
      canvas.removeEventListener('mouseleave', onLeave)
    }
  }, [graphData, width, height, onNodeClick])

  // Separate rAF loop for particle animation when sim is settled
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !sRef.current.particles.length) return
    let raf
    function particleLoop() {
      const s = sRef.current
      if (!s.animId && s.particles.length) {
        drawScene(s, canvas.getContext('2d'), canvas.width, canvas.height)
      }
      raf = requestAnimationFrame(particleLoop)
    }
    raf = requestAnimationFrame(particleLoop)
    return () => cancelAnimationFrame(raf)
  }, [graphData])

  const showLabels = sRef.current.showLabels

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block' }}
      />

      {/* Tooltip */}
      {tooltip && (
        <div
          className="graph-tooltip"
          style={{ left: tooltip.x + 14, top: tooltip.y - 52, position: 'fixed', zIndex: 9999 }}
        >
          <div className="gt-field" style={{ color: getFieldColor(tooltip.node.field_name) }}>
            {tooltip.node.field_name}
          </div>
          <div className="gt-name">
            {(tooltip.node.label || tooltip.node.cluster_id || '').slice(0, 36)}
          </div>
          <div className="gt-meta">
            <span>{tooltip.node.cluster_size?.toLocaleString()} nodes</span>
            {tooltip.node.is_anomaly && <span className="gt-anom-tag">anomaly</span>}
          </div>
        </div>
      )}

      {/* Controls overlay */}
      <div className="graph2d-controls">
        <button
          className={['g2d-btn', showLabels && 'g2d-btn--active'].filter(Boolean).join(' ')}
          onClick={toggleLabels}
          title="Toggle labels"
        >
          Labels
        </button>
        <button className="g2d-btn" onClick={resetCamera} title="Reset camera">
          Reset
        </button>
      </div>
    </div>
  )
}
