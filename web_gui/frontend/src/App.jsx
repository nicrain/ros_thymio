import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { api, getWsUrl } from './api';

const MAX_POINTS = 140;

function pushPoint(arr, value) {
  const out = [...arr, value];
  if (out.length > MAX_POINTS) out.shift();
  return out;
}

/* ── Mock signal generator (same logic as backend mock) ── */
function mockFrame() {
  const t = Date.now() / 1000;
  const alpha = 0.5 + 0.3 * Math.sin(t * 1.1) + (Math.random() - 0.5) * 0.08;
  const theta = 0.4 + 0.2 * Math.sin(t * 0.7) + (Math.random() - 0.5) * 0.06;
  const beta  = 0.3 + 0.15 * Math.sin(t * 1.6) + (Math.random() - 0.5) * 0.05;
  const tbr   = theta / (beta + 0.001);
  const fi    = alpha / (theta + 0.001);
  return {
    channels: { alpha, theta, beta },
    features: { theta_beta_ratio: tbr, focus_index: fi },
    control:  { speed_intent: Math.sin(t * 0.4) * 0.5, steer_intent: Math.sin(t * 0.3) * 0.3 },
    timestamp: t,
  };
}

/* ── Sub-component: mode card ────────────────────────────── */
function ModeCard({ value, title, desc, selected, onSelect }) {
  return (
    <label className={`mode-card${selected ? ' selected' : ''}`}>
      <input
        type="radio"
        name="input_mode"
        value={value}
        checked={selected}
        onChange={() => onSelect(value)}
      />
      <div className="mode-card-title">{title}</div>
      <div className="mode-card-desc">{desc}</div>
    </label>
  );
}

/* ── Sub-component: sub radio ───────────────────────────── */
function SubRadio({ options, value, onChange }) {
  return (
    <div className="sub-radios">
      {options.map((opt) => (
        <label
          key={opt.value}
          className={`sub-radio${value === opt.value ? ' selected' : ''}`}
        >
          <input
            type="radio"
            name="eeg_option"
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
          />
          {opt.label}
        </label>
      ))}
    </div>
  );
}

/* ── EEG sub-panel ─────────────────────────────────────── */
function EegSubPanel({ eegDevice, eegProtocol, filePath, onDevice, onProtocol, onFilePath }) {
  return (
    <div className="eeg-sub">
      <h3>EEG Device &amp; Protocol</h3>

      <span className="sub-label">Device</span>
      <SubRadio
        options={[
          { value: 'enobio', label: 'Enobio' },
          { value: 'gtec',   label: 'g.tec' },
        ]}
        value={eegDevice}
        onChange={onDevice}
      />

      <span className="sub-label">Data Source</span>
      <SubRadio
        options={[
          { value: 'tcp',         label: 'TCP' },
          { value: 'lsl',         label: 'LSL' },
          { value: 'tcp_file',    label: 'TCP File Replay' },
          { value: 'lsl_file',    label: 'LSL File Replay' },
        ]}
        value={eegProtocol}
        onChange={onProtocol}
      />

      {(eegProtocol === 'tcp_file' || eegProtocol === 'lsl_file') && (
        <div className="file-row">
          <label>File path:</label>
          <input
            type="text"
            value={filePath}
            placeholder="/path/to/recording.edf"
            onChange={(e) => onFilePath(e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

/* ── Main App ───────────────────────────────────────────── */
export default function App() {
  /* ── Config & runtime state ─────────────────────────── */
  const [config, setConfig]       = useState(null);
  const [feedback, setFeedback]   = useState('Ready.');
  const [series, setSeries]       = useState({ t: [], alpha: [], theta: [], beta: [],
                                                ratio: [], focus: [], speed: [], steer: [] });
  const [wsConnected, setWsConnected] = useState(false);

  /* ── UI mode state ─────────────────────────────────── */
  const [inputMode, setInputMode]   = useState('mock'); // 'mock' | 'eeg' | 'tobii' | 'teleop'
  const [eegDevice, setEegDevice]   = useState('enobio');
  const [eegProtocol, setEegProtocol] = useState('tcp');
  const [filePath, setFilePath]     = useState('');

  const [outputMode, setOutputMode]  = useState('thymio_simu'); // 'thymio' | 'thymio_simu' | 'none'
  const [showWaveform, setShowWaveform] = useState(true);

  const wsRef = useRef(null);

  /* ── Derived: is control mode (no waveform) ─────────── */
  const isControlMode = inputMode === 'teleop' || inputMode === 'tobii';

  /* ── Load config on mount ──────────────────────────── */
  useEffect(() => {
    api.get('/api/config')
      .then((r) => {
        setConfig(r.data.config);
        setFeedback('Config loaded.');
      })
      .catch((err) => setFeedback(`Init failed: ${err.message}`));
  }, []);

  /* ── WebSocket for real-time data ───────────────────── */
  useEffect(() => {
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (!isControlMode) {
        setSeries((prev) => ({
          t:     pushPoint(prev.t,     new Date(data.timestamp * 1000).toLocaleTimeString()),
          alpha: pushPoint(prev.alpha,  data.channels?.alpha   ?? 0),
          theta: pushPoint(prev.theta,  data.channels?.theta    ?? 0),
          beta:  pushPoint(prev.beta,   data.channels?.beta     ?? 0),
          ratio: pushPoint(prev.ratio,  data.features?.theta_beta_ratio ?? 0),
          focus: pushPoint(prev.focus,  data.features?.focus_index       ?? 0),
          speed: pushPoint(prev.speed,  data.control?.speed_intent       ?? 0),
          steer: pushPoint(prev.steer,  data.control?.steer_intent       ?? 0),
        }));
      }
    };
    ws.onclose = () => setWsConnected(false);
    return () => ws.close();
  }, [isControlMode]);

  /* ── ECharts options ─────────────────────────────────── */
  const waveOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#eaf3ff' } },
    grid: { left: 30, right: 20, top: 38, bottom: 28 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#a7bfd8', showMaxLabel: true } },
    yAxis: { type: 'value', axisLabel: { color: '#a7bfd8' } },
    series: [
      { name: 'alpha', type: 'line', smooth: true, showSymbol: false, data: series.alpha },
      { name: 'theta', type: 'line', smooth: true, showSymbol: false, data: series.theta },
      { name: 'beta',  type: 'line', smooth: true, showSymbol: false, data: series.beta  },
    ],
    color: ['#ffd166', '#06d6a0', '#4cc9f0'],
    animation: false,
  }), [series]);

  const featureOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#eaf3ff' } },
    grid: { left: 30, right: 20, top: 38, bottom: 28 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#a7bfd8', showMaxLabel: true } },
    yAxis: { type: 'value', axisLabel: { color: '#a7bfd8' } },
    series: [
      { name: 'theta_beta_ratio', type: 'line', smooth: true, showSymbol: false, data: series.ratio },
      { name: 'focus_index',       type: 'line', smooth: true, showSymbol: false, data: series.focus },
    ],
    color: ['#ff7b00', '#8ac926'],
    animation: false,
  }), [series]);

  const controlOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#eaf3ff' } },
    grid: { left: 30, right: 20, top: 38, bottom: 28 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#a7bfd8', showMaxLabel: true } },
    yAxis: { type: 'value', min: -1, max: 1, axisLabel: { color: '#a7bfd8' } },
    series: [
      { name: 'speed_intent', type: 'line', smooth: true, showSymbol: false, data: series.speed },
      { name: 'steer_intent', type: 'line', smooth: true, showSymbol: false, data: series.steer },
    ],
    color: ['#ef476f', '#118ab2'],
    animation: false,
  }), [series]);

  /* ── Build patch payload ─────────────────────────────── */
  function buildPatch() {
    const inputMap = {
      mock:    'mock',
      eeg:     eegProtocol === 'tcp' ? 'tcp_client' : eegProtocol === 'lsl' ? 'lsl' : 'file',
      tobii:   'lsl',       // gaze uses LSL bridge
      teleop:  'tcp_client',
    };

    const isSim = outputMode === 'thymio_simu';
    return {
      eeg: {
        input:         inputMap[inputMode] || 'mock',
        policy:        'focus',
        tcp_control_mode: eegProtocol.includes('tcp') ? 'feature' : 'movement',
        tcp_host:      '127.0.0.1',
        tcp_port:      1234,
        lsl_stream_type: 'EEG',
        lsl_timeout:   8.0,
        lsl_channel_map: 'alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4',
      },
      launch: {
        use_sim:          isSim,
        use_gui:          isSim,
        run_eeg:          inputMode === 'eeg' || inputMode === 'mock',
        run_gaze:         inputMode === 'tobii',
        use_teleop:       inputMode === 'teleop',
        use_tobii_bridge: inputMode === 'tobii',
        use_enobio_bridge: false,
      },
      pipeline: {
        source_type:       inputMap[inputMode] || 'mock',
        selected_channels: [0, 1, 2],
        algorithm:          'theta_beta_ratio',
      },
    };
  }

  /* ── Actions ─────────────────────────────────────────── */
  async function saveConfig() {
    try {
      await api.put('/api/config', { patch: buildPatch() });
      setFeedback('Config saved in backend memory.');
    } catch (err) {
      setFeedback(`Save failed: ${err.message}`);
    }
  }

  async function runAction(path, dryRun) {
    try {
      const res = await api.post(path, { dry_run: dryRun });
      setFeedback(`${res.data.detail}  command: ${res.data.command}`);
    } catch (err) {
      setFeedback(`Action failed: ${err.message}`);
    }
  }

  if (!config) {
    return <div className="loading">Loading dashboard...</div>;
  }

  return (
    <main className="page">

      {/* ── Hero ─────────────────────────────────── */}
      <header className="hero">
        <div>
          <p className="kicker">THYMIO CONTROL CONSOLE</p>
          <h1>Web GUI</h1>
          <p className="subtitle">
            Configure input source, output target, and monitor real-time signals.
          </p>
        </div>
        <div className="badge">
          ws: {wsConnected ? 'connected' : 'disconnected'}
        </div>
      </header>

      {/* ── Input + Output row ───────────────────── */}
      <div className="two-col-1">

        {/* Input section */}
        <div className="panel">
          <p className="section-label">Input Source</p>

          <div className="mode-cards">
            <ModeCard
              value="mock"
              title="Mock"
              desc="Simulated EEG signals"
              selected={inputMode === 'mock'}
              onSelect={setInputMode}
            />
            <ModeCard
              value="eeg"
              title="EEG"
              desc="Enobio or g.tec device"
              selected={inputMode === 'eeg'}
              onSelect={setInputMode}
            />
            <ModeCard
              value="tobii"
              title="Tobii (Gaze)"
              desc="Eye tracking → robot control"
              selected={inputMode === 'tobii'}
              onSelect={setInputMode}
            />
            <ModeCard
              value="teleop"
              title="Teleop"
              desc="Keyboard / joystick control"
              selected={inputMode === 'teleop'}
              onSelect={setInputMode}
            />
          </div>

          {inputMode === 'eeg' && (
            <EegSubPanel
              eegDevice={eegDevice}
              eegProtocol={eegProtocol}
              filePath={filePath}
              onDevice={setEegDevice}
              onProtocol={setEegProtocol}
              onFilePath={setFilePath}
            />
          )}

          <div className="btn-row">
            <button onClick={saveConfig}>Save Config</button>
            <button onClick={() => runAction('/api/system/start', true)}>Start (Dry-run)</button>
            <button className="ghost" onClick={() => runAction('/api/system/stop', true)}>Stop</button>
          </div>
        </div>

        {/* Output + status */}
        <div className="panel">
          <p className="section-label">Output Target</p>

          <div className="output-group">
            {[
              { value: 'thymio',       title: 'Thymio',        desc: 'Real robot' },
              { value: 'thymio_simu',   title: 'Thymio Simu',   desc: 'Gazebo simulation' },
              { value: 'none',          title: 'Monitor Only',  desc: 'View waveforms only' },
            ].map((opt) => (
              <label
                key={opt.value}
                className={`output-radio${outputMode === opt.value ? ' selected' : ''}`}
              >
                <input
                  type="radio"
                  name="output_mode"
                  value={opt.value}
                  checked={outputMode === opt.value}
                  onChange={() => setOutputMode(opt.value)}
                />
                <div className="output-radio-title">{opt.title}</div>
                <div className="output-radio-desc">{opt.desc}</div>
              </label>
            ))}
          </div>

          <label className={`waveform-toggle${isControlMode ? ' disabled' : ''}`}>
            <input
              type="checkbox"
              checked={showWaveform}
              disabled={isControlMode}
              onChange={(e) => setShowWaveform(e.target.checked)}
            />
            <span>Show Waveforms</span>
            <small>{isControlMode ? '— not available for this mode' : 'alpha / theta / beta / features / control'}</small>
          </label>

          <p className="section-label" style={{ marginTop: 18 }}>System Status</p>
          <div className="status-item">
            <div className={`status-dot ${wsConnected ? 'ok' : 'warn'}`} />
            <span className="status-item-label">WebSocket</span>
            <span className="status-item-value">{wsConnected ? 'connected' : 'disconnected'}</span>
          </div>
          <div className="status-item">
            <div className="status-dot off" />
            <span className="status-item-label">ROS2</span>
            <span className="status-item-value">—</span>
          </div>
          <div className="status-item">
            <div className="status-dot off" />
            <span className="status-item-label">Thymio</span>
            <span className="status-item-value">—</span>
          </div>
        </div>

      </div>

      {/* ── Waveform section ─────────────────────── */}
      <div className={`charts-section${!showWaveform || isControlMode ? ' dimmed' : ''}`}>
        <div className="charts-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
          <div className="panel chart-panel">
            <h2>Raw Wave (alpha / theta / beta)</h2>
            <ReactECharts option={waveOption} style={{ height: 260 }} />
          </div>
          <div className="panel chart-panel">
            <h2>Feature Trends</h2>
            <ReactECharts option={featureOption} style={{ height: 260 }} />
          </div>
          <div className="panel chart-panel">
            <h2>Control Intents</h2>
            <ReactECharts option={controlOption} style={{ height: 260 }} />
          </div>
        </div>
      </div>

      <footer className="footer-log">{feedback}</footer>
    </main>
  );
}
