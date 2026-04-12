import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { api, getWsUrl } from './api';

const EMPTY_STATUS = {
  mode: 'mock',
  ros_available: false,
  thymio_connected: false,
  thymio_probe_detail: 'N/A',
  eeg_stream_alive: false,
  running: false,
  last_error: null,
};

const MAX_POINTS = 140;

function pushPoint(arr, value) {
  const out = [...arr, value];
  if (out.length > MAX_POINTS) {
    out.shift();
  }
  return out;
}

function setNested(obj, path, value) {
  const keys = path.split('.');
  const clone = structuredClone(obj);
  let cur = clone;
  for (let i = 0; i < keys.length - 1; i += 1) {
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
  return clone;
}

export default function App() {
  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState(EMPTY_STATUS);
  const [feedback, setFeedback] = useState('Ready.');
  const [series, setSeries] = useState({
    t: [],
    alpha: [],
    theta: [],
    beta: [],
    ratio: [],
    focus: [],
    speed: [],
    steer: [],
  });

  const wsRef = useRef(null);

  useEffect(() => {
    async function init() {
      try {
        const [cfg, st] = await Promise.all([api.get('/api/config'), api.get('/api/status')]);
        setConfig(cfg.data.config);
        setStatus(st.data);
        setFeedback('Config loaded.');
      } catch (err) {
        setFeedback(`Init failed: ${err.message}`);
      }
    }
    init();
  }, []);

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const st = await api.get('/api/status');
        setStatus(st.data);
      } catch {
        // ignore polling errors for prototype
      }
    }, 2500);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status || EMPTY_STATUS);
      setSeries((prev) => ({
        t: pushPoint(prev.t, new Date(data.timestamp * 1000).toLocaleTimeString()),
        alpha: pushPoint(prev.alpha, data.channels?.alpha ?? 0),
        theta: pushPoint(prev.theta, data.channels?.theta ?? 0),
        beta: pushPoint(prev.beta, data.channels?.beta ?? 0),
        ratio: pushPoint(prev.ratio, data.features?.theta_beta_ratio ?? 0),
        focus: pushPoint(prev.focus, data.features?.focus_index ?? 0),
        speed: pushPoint(prev.speed, data.control?.speed_intent ?? 0),
        steer: pushPoint(prev.steer, data.control?.steer_intent ?? 0),
      }));
    };

    ws.onclose = () => {
      setFeedback('WebSocket disconnected.');
    };

    return () => ws.close();
  }, []);

  const waveOption = useMemo(
    () => ({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#eaf3ff' } },
      grid: { left: 30, right: 20, top: 38, bottom: 28 },
      xAxis: { type: 'category', data: series.t, axisLabel: { color: '#a7bfd8', showMaxLabel: true } },
      yAxis: { type: 'value', axisLabel: { color: '#a7bfd8' } },
      series: [
        { name: 'alpha', type: 'line', smooth: true, showSymbol: false, data: series.alpha },
        { name: 'theta', type: 'line', smooth: true, showSymbol: false, data: series.theta },
        { name: 'beta', type: 'line', smooth: true, showSymbol: false, data: series.beta },
      ],
      color: ['#ffd166', '#06d6a0', '#4cc9f0'],
      animation: false,
    }),
    [series]
  );

  const featureOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#eaf3ff' } },
      grid: { left: 30, right: 20, top: 38, bottom: 28 },
      xAxis: { type: 'category', data: series.t, axisLabel: { color: '#a7bfd8', showMaxLabel: true } },
      yAxis: { type: 'value', axisLabel: { color: '#a7bfd8' } },
      series: [
        { name: 'theta_beta_ratio', type: 'line', smooth: true, showSymbol: false, data: series.ratio },
        { name: 'focus_index', type: 'line', smooth: true, showSymbol: false, data: series.focus },
      ],
      color: ['#ff7b00', '#8ac926'],
      animation: false,
    }),
    [series]
  );

  const controlOption = useMemo(
    () => ({
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
    }),
    [series]
  );

  async function saveConfig() {
    try {
      await api.put('/api/config', { patch: config });
      setFeedback('Config saved in backend memory.');
    } catch (err) {
      setFeedback(`Save failed: ${err.message}`);
    }
  }

  async function runAction(path, dryRun) {
    try {
      const res = await api.post(path, { dry_run: dryRun });
      setFeedback(`${res.data.detail} command: ${res.data.command}`);
      const st = await api.get('/api/status');
      setStatus(st.data);
    } catch (err) {
      setFeedback(`Action failed: ${err.message}`);
    }
  }

  function renderToggle(path, label) {
    const val = path.split('.').reduce((acc, key) => acc?.[key], config);
    return (
      <label className="toggle-row" key={path}>
        <span>{label}</span>
        <input
          type="checkbox"
          checked={Boolean(val)}
          onChange={(e) => setConfig((prev) => setNested(prev, path, e.target.checked))}
        />
      </label>
    );
  }

  function renderInput(path, label, type = 'text') {
    const val = path.split('.').reduce((acc, key) => acc?.[key], config);
    return (
      <label className="input-row" key={path}>
        <span>{label}</span>
        <input
          type={type}
          value={val ?? ''}
          onChange={(e) => {
            const raw = e.target.value;
            const next = type === 'number' ? Number(raw) : raw;
            setConfig((prev) => setNested(prev, path, next));
          }}
        />
      </label>
    );
  }

  function renderChannelList(path, label) {
    const val = path.split('.').reduce((acc, key) => acc?.[key], config);
    const text = Array.isArray(val) ? val.join(',') : '';
    return (
      <label className="input-row" key={path}>
        <span>{label}</span>
        <input
          type="text"
          value={text}
          onChange={(e) => {
            const parsed = e.target.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
              .map((s) => Number(s))
              .filter((n) => Number.isFinite(n));
            setConfig((prev) => setNested(prev, path, parsed));
          }}
        />
      </label>
    );
  }

  if (!config) {
    return <div className="loading">Loading dashboard...</div>;
  }

  return (
    <main className="page">
      <header className="hero">
        <div>
          <p className="kicker">THYMIO CONTROL CONSOLE</p>
          <h1>Web GUI Prototype</h1>
          <p className="subtitle">
            Supports mock-first runtime, parameter editing, status probes, and real-time EEG visualization.
          </p>
        </div>
        <div className="badge">mode: {status.mode}</div>
      </header>

      <section className="status-grid">
        <article className={`status-card ${status.thymio_connected ? 'ok' : 'warn'}`}>
          <h3>Thymio</h3>
          <p>{status.thymio_connected ? 'Connected' : 'Not detected'}</p>
          <small>{status.thymio_probe_detail}</small>
        </article>
        <article className={`status-card ${status.ros_available ? 'ok' : 'warn'}`}>
          <h3>ROS2</h3>
          <p>{status.ros_available ? 'Available' : 'Unavailable'}</p>
          <small>Probe by ros2 executable in PATH</small>
        </article>
        <article className={`status-card ${status.eeg_stream_alive ? 'ok' : 'warn'}`}>
          <h3>EEG Stream</h3>
          <p>{status.eeg_stream_alive ? 'Flowing' : 'Idle'}</p>
          <small>Derived from backend runtime state</small>
        </article>
        <article className={`status-card ${status.running ? 'ok' : ''}`}>
          <h3>Runtime</h3>
          <p>{status.running ? 'Running' : 'Stopped'}</p>
          <small>{status.last_error || 'No active error'}</small>
        </article>
      </section>

      <section className="controls-grid">
        <article className="panel">
          <h2>Launch Controls</h2>
          {renderToggle('launch.use_sim', 'Use Simulation')}
          {renderToggle('launch.use_gui', 'Gazebo GUI')}
          {renderToggle('launch.run_eeg', 'Run EEG Node')}
          {renderToggle('launch.run_gaze', 'Run Gaze Node')}
          {renderToggle('launch.use_teleop', 'Use Teleop')}
          {renderToggle('launch.use_tobii_bridge', 'Use Tobii Bridge')}
          {renderToggle('launch.use_enobio_bridge', 'Use Enobio Bridge')}

          <div className="btn-row">
            <button onClick={saveConfig}>Save Config</button>
            <button onClick={() => runAction('/api/system/start', true)}>Start (Dry-run)</button>
            <button className="ghost" onClick={() => runAction('/api/system/stop', true)}>
              Stop
            </button>
          </div>
        </article>

        <article className="panel">
          <h2>Input & LSL</h2>
          {renderInput('eeg.input', 'Input Mode')}
          {renderInput('eeg.policy', 'Policy')}
          {renderInput('eeg.tcp_control_mode', 'TCP Control Mode')}
          {renderInput('eeg.tcp_host', 'TCP Host')}
          {renderInput('eeg.tcp_port', 'TCP Port', 'number')}
          {renderInput('eeg.lsl_stream_type', 'LSL Stream Type')}
          {renderInput('eeg.lsl_timeout', 'LSL Timeout (s)', 'number')}
          {renderInput('eeg.lsl_channel_map', 'LSL Channel Map')}

          <h3>Signal Filter (UI-first)</h3>
          {renderToggle('filter.enabled', 'Enable Filter')}
          {renderInput('filter.type', 'Filter Type')}
          {renderInput('filter.low_hz', 'Low Cut (Hz)', 'number')}
          {renderInput('filter.high_hz', 'High Cut (Hz)', 'number')}
          {renderInput('filter.notch_hz', 'Notch (Hz)', 'number')}
          {renderInput('filter.order', 'Order', 'number')}
        </article>

        <article className="panel">
          <h2>Motion & Pipeline</h2>
          {renderInput('motion.max_forward_speed', 'Max Forward Speed', 'number')}
          {renderInput('motion.reverse_speed', 'Reverse Speed', 'number')}
          {renderInput('motion.turn_forward_speed', 'Turn Forward Speed', 'number')}
          {renderInput('motion.turn_angular_speed', 'Turn Angular Speed', 'number')}
          {renderInput('motion.reverse_threshold', 'Reverse Threshold', 'number')}
          {renderInput('motion.steer_deadzone', 'Steer Deadzone', 'number')}
          {renderInput('motion.line_mode', 'Line Mode')}

          {renderInput('pipeline.source_type', 'Pipeline Source')}
          {renderInput('pipeline.algorithm', 'Pipeline Algorithm')}
          {renderChannelList('pipeline.selected_channels', 'Selected Channels (comma list)')}
        </article>
      </section>

      <section className="charts-grid">
        <article className="panel chart-panel">
          <h2>Raw Wave (alpha/theta/beta)</h2>
          <ReactECharts option={waveOption} style={{ height: 280 }} />
        </article>
        <article className="panel chart-panel">
          <h2>Feature Trends</h2>
          <ReactECharts option={featureOption} style={{ height: 280 }} />
        </article>
        <article className="panel chart-panel">
          <h2>Control Intents</h2>
          <ReactECharts option={controlOption} style={{ height: 280 }} />
        </article>
      </section>

      <footer className="footer-log">{feedback}</footer>
    </main>
  );
}
