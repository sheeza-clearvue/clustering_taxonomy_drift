import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { getAnomalyTypeColor, getAnomalyTypeLabel } from '../../utils/colors.js'

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div className="chart-tooltip">
      <div className="ct-label">{getAnomalyTypeLabel(name)}</div>
      <div className="ct-row"><strong>{value}</strong> anomalies</div>
    </div>
  )
}

const renderCustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }) => {
  if (percent < 0.07) return null
  const RADIAN = Math.PI / 180
  const r  = innerRadius + (outerRadius - innerRadius) * 0.5
  const x  = cx + r * Math.cos(-midAngle * RADIAN)
  const y  = cy + r * Math.sin(-midAngle * RADIAN)
  return (
    <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {(percent * 100).toFixed(0)}%
    </text>
  )
}

export default function AnomalyRingChart({ byType }) {
  if (!byType || !Object.keys(byType).length) {
    return <div className="chart-empty">No anomaly data</div>
  }

  const data = Object.entries(byType).map(([type, count]) => ({
    name: type, value: count,
  }))

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={90}
          paddingAngle={3}
          dataKey="value"
          labelLine={false}
          label={renderCustomLabel}
        >
          {data.map(entry => (
            <Cell key={entry.name} fill={getAnomalyTypeColor(entry.name)} />
          ))}
        </Pie>
        <Tooltip content={<CustomTooltip />} />
        <Legend
          formatter={v => <span style={{ color: '#cccccc', fontSize: 11 }}>{getAnomalyTypeLabel(v)}</span>}
          iconSize={10}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}
