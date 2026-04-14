import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { api, getWsUrl } from './api';

/* ── Constants ─────────────────────────────────────────── */
const MAX_POINTS = 140;

/* ── Helpers ───────────────────────────────────────────── */
function pushPoint(arr, value) {
  const out = [...arr, value];
  if (out.length > MAX_POINTS) out.shift();
  return out;
}

/* ── Hero: Thymio robot icon ─────────────────────────────── */
function HeroEmblem() {
  return (
    <div className="hero-emblem">
      <img
        src="https://play-lh.googleusercontent.com/_S_Xg6eG0b3rFbtPrc9DVd2DbFbM71_1YO9HZQqxGnYyKy8SuPmtfE9m_ynqxj_WTIw=w600-h300-pc0xffffff-pd"
        alt="Thymio"
      />
    </div>
  );
}

/* ── Mode Card ─────────────────────────────────────────── */
function ModeCard({ value, title, desc, icon, selected, onSelect }) {
  return (
    <label className={`mode-card${selected ? ' selected' : ''}`}>
      <input
        type="radio"
        name="input_mode"
        value={value}
        checked={selected}
        onChange={() => onSelect(value)}
      />
      <span className="mode-card-icon">{icon}</span>
      <span className="mode-card-title">{title}</span>
      <span className="mode-card-desc">{desc}</span>
    </label>
  );
}

/* ── Camera Panel ──────────────────────────────────────── */
function CameraPanel() {
  const [frame, setFrame] = useState(null);
  const [camWsConnected, setCamWsConnected] = useState(false);
  const [camError, setCamError] = useState(null);
  const camWsRef = useRef(null);

  useEffect(() => {
    if (wsRef.current) wsRef.current.close();
    const wsUrl = (import.meta.env.VITE_API_BASE || '').replace(/^http/, 'ws') + '/ws/gazebo_frame';
    const ws = new WebSocket(wsUrl);
    camWsRef.current = ws;

    ws.onopen  = () => { setCamWsConnected(true); setCamError(null); };
    ws.onclose = () => { setCamWsConnected(false); };
    ws.onerror = () => { setCamError('connection error'); };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.error) {
        setCamError(data.error);
        return;
      }
      if (data.image) {
        setFrame(`data:image/jpeg;base64,${data.image}`);
        setCamError(null);
      }
    };
    return () => ws.close();
  }, []);

  return (
    <div className="camera-panel">
      <div className="camera-header">
        <span className="section-label">02b — Gazebo View</span>
        <div className={`cam-status-dot ${camWsConnected ? 'ok' : 'warn'}`} />
        <span className="cam-status-text">
          {camWsConnected ? 'live' : camError ? camError : 'connecting…'}
        </span>
      </div>
      <div className="camera-frame-wrapper">
        {frame
          ? <img src={frame} alt="Gazebo overhead view" className="camera-frame" />
          : <div className="camera-placeholder">
              {camError ? `Camera: ${camError}` : 'Waiting for stream…'}
            </div>
        }
      </div>
    </div>
  );
}

/* ── Sub Radio group ──────────────────────────────────── */
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

/* ── EEG sub-panel (white editorial card) ──────────────── */
function EegSubPanel({ eegDevice, eegProtocol, filePath, onDevice, onProtocol, onFilePath }) {
  return (
    <div className="eeg-sub-panel">
      <h3>EEG — Device &amp; Protocol</h3>

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
          { value: 'tcp',      label: 'TCP' },
          { value: 'lsl',      label: 'LSL' },
          { value: 'tcp_file', label: 'TCP File Replay' },
          { value: 'lsl_file', label: 'LSL File Replay' },
        ]}
        value={eegProtocol}
        onChange={onProtocol}
      />

      {(eegProtocol === 'tcp_file' || eegProtocol === 'lsl_file') && (
        <div className="file-row">
          <label>File:</label>
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

/* ── App ───────────────────────────────────────────────── */
export default function App() {
  /* ── State ─────────────────────────────────────────── */
  const [config, setConfig]         = useState(null);
  const [feedback, setFeedback]     = useState('Ready.');
  const [series, setSeries]         = useState({
    t: [], alpha: [], theta: [], beta: [],
    ratio: [], focus: [], speed: [], steer: [],
  });
  const [wsConnected, setWsConnected] = useState(false);

  /* ── UI mode state ─────────────────────────────────── */
  const [inputMode, setInputMode]       = useState('mock');
  const [eegDevice, setEegDevice]       = useState('enobio');
  const [eegProtocol, setEegProtocol]   = useState('tcp');
  const [filePath, setFilePath]         = useState('');

  const [outputMode, setOutputMode]         = useState('thymio_simu');
  const [showWaveform, setShowWaveform]     = useState(true);

  const wsRef = useRef(null);

  /* ── Derived ────────────────────────────────────────── */
  const isControlMode = inputMode === 'teleop' || inputMode === 'tobii';

  /* ── Load config ────────────────────────────────────── */
  useEffect(() => {
    api.get('/api/config')
      .then((r) => { setConfig(r.data.config); setFeedback('Config loaded.'); })
      .catch((err) => setFeedback(`Init failed: ${err.message}`));
  }, []);

  /* ── WebSocket ──────────────────────────────────────── */
  useEffect(() => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen  = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (!isControlMode) {
        setSeries((prev) => ({
          t:     pushPoint(prev.t,     new Date(data.timestamp * 1000).toLocaleTimeString()),
          alpha: pushPoint(prev.alpha,  data.channels?.alpha             ?? 0),
          theta: pushPoint(prev.theta,  data.channels?.theta             ?? 0),
          beta:  pushPoint(prev.beta,   data.channels?.beta               ?? 0),
          ratio: pushPoint(prev.ratio,  data.features?.theta_beta_ratio   ?? 0),
          focus: pushPoint(prev.focus,  data.features?.focus_index        ?? 0),
          speed: pushPoint(prev.speed,  data.control?.speed_intent        ?? 0),
          steer: pushPoint(prev.steer,  data.control?.steer_intent        ?? 0),
        }));
      }
    };
    return () => ws.close();
  }, [isControlMode]);

  /* ── ECharts options (light theme for white panel) ──── */
  const waveOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#ddd', textStyle: { color: '#333' } },
    legend: { textStyle: { color: '#555' }, top: 2 },
    grid: { left: 28, right: 16, top: 36, bottom: 24 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#999', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: '#999', fontSize: 10 } },
    series: [
      { name: 'alpha', type: 'line', smooth: true, showSymbol: false, data: series.alpha },
      { name: 'theta', type: 'line', smooth: true, showSymbol: false, data: series.theta },
      { name: 'beta',  type: 'line', smooth: true, showSymbol: false, data: series.beta  },
    ],
    color: ['#DA291C', '#F6E500', '#000000'],
    animation: false,
  }), [series]);

  const featureOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#ddd', textStyle: { color: '#333' } },
    legend: { textStyle: { color: '#555' }, top: 2 },
    grid: { left: 28, right: 16, top: 36, bottom: 24 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#999', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: '#999', fontSize: 10 } },
    series: [
      { name: 'theta_beta_ratio', type: 'line', smooth: true, showSymbol: false, data: series.ratio },
      { name: 'focus_index',       type: 'line', smooth: true, showSymbol: false, data: series.focus },
    ],
    color: ['#F6E500', '#000000'],
    animation: false,
  }), [series]);

  const controlOption = useMemo(() => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#ddd', textStyle: { color: '#333' } },
    legend: { textStyle: { color: '#555' }, top: 2 },
    grid: { left: 28, right: 16, top: 36, bottom: 24 },
    xAxis: { type: 'category', data: series.t, axisLabel: { color: '#999', fontSize: 10 } },
    yAxis: { type: 'value', min: -1, max: 1, axisLabel: { color: '#999', fontSize: 10 } },
    series: [
      { name: 'speed_intent', type: 'line', smooth: true, showSymbol: false, data: series.speed },
      { name: 'steer_intent', type: 'line', smooth: true, showSymbol: false, data: series.steer },
    ],
    color: ['#DA291C', '#000000'],
    animation: false,
  }), [series]);

  /* ── Build patch ─────────────────────────────────────── */
  function buildPatch() {
    const inputMap = {
      mock:    'mock',
      eeg:     eegProtocol === 'tcp' ? 'tcp_client' : eegProtocol === 'lsl' ? 'lsl' : 'file',
      tobii:   'lsl',
      teleop:  'tcp_client',
    };
    const isSim = outputMode === 'thymio_simu';
    return {
      eeg: {
        input:           inputMap[inputMode] || 'mock',
        policy:          'focus',
        tcp_control_mode: 'feature',
        tcp_host:        '127.0.0.1',
        tcp_port:        1234,
        lsl_stream_type: 'EEG',
        lsl_timeout:     8.0,
        lsl_channel_map: 'alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4',
      },
      launch: {
        use_sim:           isSim,
        use_gui:           isSim,
        run_eeg:           inputMode === 'eeg' || inputMode === 'mock',
        run_gaze:          inputMode === 'tobii',
        use_teleop:        inputMode === 'teleop',
        use_tobii_bridge:  inputMode === 'tobii',
        use_enobio_bridge: false,
      },
      pipeline: {
        source_type:       inputMap[inputMode] || 'mock',
        selected_channels: [0, 1, 2],
        algorithm:         'theta_beta_ratio',
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
      throw err;
    }
  }

  async function startSystem() {
    try {
      await saveConfig();
      await runAction('/api/system/start', true);
    } catch (err) {
      if (!String(err?.message || err).includes('Save failed')) {
        setFeedback(`Start failed: ${err.message}`);
      }
    }
  }

  async function runAction(path, dryRun) {
    try {
      const res = await api.post(path, { dry_run: dryRun });
      setFeedback(`${res.data.detail}  —  ${res.data.command}`);
    } catch (err) {
      setFeedback(`Action failed: ${err.message}`);
    }
  }

  /* ── Render ───────────────────────────────────────────── */
  if (!config) {
    return <div className="loading">Loading dashboard&hellip;</div>;
  }

  return (
    <div className="page">

      {/* ── TOP BAR ───────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <HeroEmblem />
          <span className="topbar-title">Thymio EEG Control</span>
        </div>
        <div className={`topbar-status ${wsConnected ? 'ok' : 'warn'}`}>
          <span className="status-dot-wrapper">
            <span className={`status-dot ${wsConnected ? 'ok' : 'warn'}`} />
          </span>
          <span className="topbar-status-text">WebSocket {wsConnected ? 'connected' : 'disconnected'}</span>
        </div>
      </header>

      {/* ── SECTION 2: Controls (Dark surface) ────────── */}
      <div className="section-dark">
        <div className="controls-grid">

          {/* LEFT — Input Source */}
          <div>
            <span className="section-label">01 — Input Source</span>
            <div className="mode-cards">
              <ModeCard
                value="mock"
                title="Mock"
                desc="Simulated EEG signals"
                icon="◈"
                selected={inputMode === 'mock'}
                onSelect={setInputMode}
              />
              <ModeCard
                value="eeg"
                title="EEG"
                desc="Enobio / g.tec device"
                icon="◉"
                selected={inputMode === 'eeg'}
                onSelect={setInputMode}
              />
              <ModeCard
                value="tobii"
                title="Tobii"
                desc="Eye tracking → robot"
                icon="◎"
                selected={inputMode === 'tobii'}
                onSelect={setInputMode}
              />
              <ModeCard
                value="teleop"
                title="Keyboard"
                desc="Keyboard / joystick"
                icon="⊕"
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
              <button className="btn btn-cta"     onClick={startSystem}>Start</button>
              <button className="btn btn-ghost"   onClick={() => runAction('/api/system/stop',  true)}>Stop</button>
            </div>
          </div>

          {/* RIGHT — Output Target */}
          <div>
            <span className="section-label">02 — Output Target</span>

            <div className="output-radios">
              {[
                { value: 'thymio',        title: 'Thymio',       desc: 'Real robot' },
                { value: 'thymio_simu',   title: 'Thymio Simu',  desc: 'Gazebo simulation' },
                { value: 'none',          title: 'Monitor Only', desc: 'View waveforms only' },
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
                  <span className="output-radio-title">{opt.title}</span>
                  <span className="output-radio-desc">{opt.desc}</span>
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
              <span className="waveform-toggle-text">Show Waveforms</span>
              <span className="waveform-toggle-note">
                {isControlMode ? '— unavailable for this mode' : 'alpha · theta · beta · features · control'}
              </span>
            </label>

            <div className="status-strip">
              <div className="status-row">
                <div className={`status-dot ${wsConnected ? 'ok' : 'warn'}`} />
                <span className="status-label">WebSocket</span>
                <span className="status-value">{wsConnected ? 'connected' : 'disconnected'}</span>
              </div>
              <div className="status-row">
                <div className="status-dot off" />
                <span className="status-label">ROS2</span>
                <span className="status-value">—</span>
              </div>
              <div className="status-row">
                <div className="status-dot off" />
                <span className="status-label">Thymio</span>
                <span className="status-value">—</span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* ── SECTION 2b: Gazebo Camera Stream ─────────────── */}
      <CameraPanel />

      {/* ── SECTION 3: Waveforms (White editorial panel) ─ */}
      <div className="section-light">
        <span className="section-label">03 — Real-time Signals</span>
        <h2 className="section-heading">Signal Monitoring</h2>

        <div className={`charts-grid${!showWaveform || isControlMode ? ' dimmed' : ''}`}>
          <div className="chart-card">
            <h3>Raw Wave &mdash; alpha / theta / beta</h3>
            <ReactECharts option={waveOption} style={{ height: 220 }} />
          </div>
          <div className="chart-card">
            <h3>Feature Trends</h3>
            <ReactECharts option={featureOption} style={{ height: 220 }} />
          </div>
          <div className="chart-card">
            <h3>Control Intents</h3>
            <ReactECharts option={controlOption} style={{ height: 220 }} />
          </div>
        </div>
      </div>

      {/* ── Footer ────────────────────────────────────── */}
      <footer className="footer">
        <span className="footer-log">{feedback}</span>
        <span className="footer-badge">Thymio Control Console</span>
      </footer>

    </div>
  );
}
