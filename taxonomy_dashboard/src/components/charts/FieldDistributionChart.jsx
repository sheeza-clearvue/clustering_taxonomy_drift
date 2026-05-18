import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts'
import { getFieldColor } from '../../utils/colors.js'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="ct-label">{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="ct-row">
          <span className="ct-dot" style={{ background: p.fill || p.color }} />
          <span>{p.name}: </span>
          <strong>{p.value?.toLocaleString()}</strong>
        </div>
      ))}
    </div>
  )
}

export default function FieldDistributionChart({ data }) {
  if (!data?.length) return <div className="chart-empty">No field data</div>

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 40 }}>
        <XAxis
          dataKey="field_name"
          tick={{ fill: '#858585', fontSize: 10 }}
          angle={-35}
          textAnchor="end"
          interval={0}
        />
        <YAxis tick={{ fill: '#858585', fontSize: 10 }} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="total" name="Clusters" radius={[3, 3, 0, 0]}>
          {data.map(entry => (
            <Cell key={entry.field_name} fill={getFieldColor(entry.field_name)} fillOpacity={0.8} />
          ))}
        </Bar>
        <Bar dataKey="anomalies" name="Anomalies" fill="#f44747" fillOpacity={0.7} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
