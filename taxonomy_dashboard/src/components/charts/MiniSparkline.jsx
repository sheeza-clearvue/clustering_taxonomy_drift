import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts'

export default function MiniSparkline({ data = [], dataKey = 'value', color = '#569cd6', height = 36 }) {
  if (!data.length) return <div style={{ height }} />

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        <Tooltip
          contentStyle={{ background: '#2d2d30', border: '1px solid #3e3e42', borderRadius: 4, fontSize: 11, padding: '4px 8px' }}
          labelStyle={{ display: 'none' }}
          itemStyle={{ color: '#cccccc' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
