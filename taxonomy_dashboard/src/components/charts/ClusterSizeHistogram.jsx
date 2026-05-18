import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="ct-label">Size bucket: {label}</div>
      <div className="ct-row">
        <strong>{payload[0]?.value?.toLocaleString()}</strong> clusters
      </div>
    </div>
  )
}

export default function ClusterSizeHistogram({ data }) {
  if (!data?.length) return <div className="chart-empty">No distribution data</div>

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 4 }}>
        <XAxis dataKey="bucket" tick={{ fill: '#858585', fontSize: 10 }} />
        <YAxis tick={{ fill: '#858585', fontSize: 10 }} />
        <Tooltip content={<CustomTooltip />} />
        <Bar
          dataKey="count"
          name="Clusters"
          fill="#569cd6"
          fillOpacity={0.75}
          radius={[3, 3, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
