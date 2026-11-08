import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { TransformComponent, TransformWrapper } from 'react-zoom-pan-pinch';
import {
  AlertTriangle, ArrowDownToLine, Check, ChevronDown, Copy, Download,
  FileJson, Info, Maximize2, Plus, RefreshCw, Settings2, Trash2, Upload, X,
} from 'lucide-react';
import type {
  AnalyzeResponse, ApiErrorCode, Bit, Circuit, CircuitMode, CircuitNode,
  GateShape, Operator, Preset,
} from './api/types';
import { api, ApiClientError } from './api/client';
import { evaluateCircuit, getUpstreamCone } from './utils/circuit-evaluator';
import { buildErrorCaret } from './utils/error-caret';
import { denseOutputs } from './utils/dense-outputs';
import { SimplifyView } from './components/SimplifyView';
import { loadCustomPresets, loadPreferences, saveCustomPresets, savePreferences } from './utils/storage';
import { copyText, downloadText, truthTableToCSV, truthTableToTSV } from './utils/formatters';

const DRAWN_BY = 'ALI';
const EXAMPLES = ["x'y + xy'", 'x ^ y', "A B + A' C", "(a + b)'", 'a nand b', 'x + yz', "x'y + z*xyz' + x'y'"];
const MODES: { value: CircuitMode; label: string }[] = [
  { value: 'expression', label: 'AS TYPED' },
  { value: 'sop', label: 'SUM OF PRODUCTS' },
  { value: 'pos', label: 'PRODUCT OF SUMS' },
];

type AppError = { code: ApiErrorCode | 'network_error'; message: string; position?: number };
type ToastState = string | null;

function useToast() {
  const [toast, setToast] = useState<ToastState>(null);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);
  return { toast, setToast };
}

function SectionTitle({ number, title }: { number: string; title: string }) {
  return <div className="section-heading"><span>{number}</span><h2>{title}</h2><i /></div>;
}

function Note({ children, hazard = false }: { children: React.ReactNode; hazard?: boolean }) {
  return <div className={`note drafted-box ${hazard ? 'hazard' : ''}`}>{children}</div>;
}

function App() {
  const initial = useMemo(() => loadPreferences(), []);
  const [expression, setExpression] = useState(initial.expression);
  const [presetName, setPresetName] = useState(initial.preset);
  const [mode, setMode] = useState<CircuitMode>(initial.mode);
  const [customPresets, setCustomPresets] = useState<Preset[]>(() => loadCustomPresets());
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<AppError | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [notationOpen, setNotationOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const { toast, setToast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<'lab' | 'guide' | 'reverse' | 'simplify'>('lab');
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const { data: builtIns = [], isError: presetLoadError } = useQuery({
    queryKey: ['presets'],
    queryFn: ({ signal }) => api.getPresets(signal),
  });

  const activeCustom = customPresets.find((p) => p.name === presetName) ?? null;
  const activePreset = activeCustom ?? builtIns.find((p) => p.name === presetName) ?? builtIns[0] ?? null;
  const presets = [...builtIns, ...customPresets];

  const runAnalysis = useCallback(async (value = expression, selectedPreset = presetName, selectedMode = mode) => {
    if (!value.trim()) {
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const custom = customPresets.find((p) => p.name === selectedPreset) ?? null;
      const data = await api.analyze({
        expression: value,
        preset: custom ? 'universal' : selectedPreset,
        custom_preset: custom,
        circuit_mode: selectedMode,
      }, controller.signal);
      if (!controller.signal.aborted) {
        setResult(data);
        setError(null);
        setActiveIndex(null);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      if (caught instanceof ApiClientError) {
        setError({ code: caught.code, message: caught.message, position: caught.position });
      } else {
        setError({ code: 'network_error', message: 'NO CONNECTION TO DRAFTING SERVER' });
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [expression, presetName, mode, customPresets]);

  useEffect(() => {
    savePreferences({ expression, preset: presetName, mode });
  }, [expression, presetName, mode]);

  useEffect(() => {
    abortRef.current?.abort();
    if (!expression.trim()) {
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => void runAnalysis(), 500);
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [expression, presetName, mode, runAnalysis]);

  useEffect(() => {
    if (initial.expression.trim()) void runAnalysis(initial.expression, initial.preset, initial.mode);
    return () => abortRef.current?.abort();
    // Initial shared URL/local preference is intentionally analyzed once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { saveCustomPresets(customPresets); }, [customPresets]);

  const updateCustomPresets = (next: Preset[]) => {
    setCustomPresets(next);
    saveCustomPresets(next);
  };

  const insertAtCursor = (symbol: string) => {
    const el = inputRef.current;
    if (!el) {
      setExpression((current) => `${current}${symbol}`);
      return;
    }
    const start = el.selectionStart ?? expression.length;
    const end = el.selectionEnd ?? start;
    const next = `${expression.slice(0, start)}${symbol}${expression.slice(end)}`;
    setExpression(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + symbol.length, start + symbol.length);
    });
  };

  const addExample = (value: string) => insertAtCursor(value);

  const copy = async (value: string) => {
    try { await copyText(value); setToast('COPIED TO CLIPBOARD'); }
    catch { setToast('CLIPBOARD ACCESS UNAVAILABLE'); }
  };

  const retry = () => void runAnalysis();

  return (
    <main className="page-shell">
      <svg className="filter-defs" aria-hidden="true" focusable="false"><defs><filter id="draft-roughness" x="-2%" y="-2%" width="104%" height="104%"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="1" seed="4" result="draft-noise" /><feDisplacementMap in="SourceGraphic" in2="draft-noise" scale="1" xChannelSelector="R" yChannelSelector="G" /></filter></defs></svg>
      {loading && <div className="progress-line" />}
      <div className="sheet">
        <div className="sheet-ticks" aria-hidden="true" />
        <header className="masthead">
          <div className="brand-mark"><span className="brand-square">B</span><div><div className="brand-title">BOOLEAN LAB</div><div className="brand-subtitle">LOGIC ENGINEERING / MACHINE STRUCTURE</div></div></div>
          <div className="header-meta"><span>LABORATORY SERIES</span><span>VOL. 01 — 2026</span><span className="status-dot">SYSTEM {presetLoadError ? 'OFFLINE' : 'READY'}</span></div>
        </header>
        <nav className="main-tabs" aria-label="Main sections">
          <button className={view === 'lab' ? 'active' : ''} onClick={() => setView('lab')}>01 / LAB</button>
          <button className={view === 'guide' ? 'active' : ''} onClick={() => setView('guide')}>02 / GUIDE</button>
          <button className={view === 'reverse' ? 'active' : ''} onClick={() => setView('reverse')}>03 / TABLE → FUNCTION</button>
          <button className={view === 'simplify' ? 'active' : ''} onClick={() => setView('simplify')}>04 / SIMPLIFY</button>
        </nav>

        {view === 'lab' && <>
        <section className="input-section drafted-box">
          <SectionTitle number="01" title="INPUT" />
          <div className="input-row">
            <label className="formula-prefix" htmlFor="function-input">F =</label>
            <input
              id="function-input"
              ref={inputRef}
              className="function-input"
              type="text"
              value={expression}
              onChange={(event) => setExpression(event.target.value.slice(0, 300))}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  if (timerRef.current !== null) window.clearTimeout(timerRef.current);
                  void runAnalysis();
                }
              }}
              placeholder="TYPE A BOOLEAN FUNCTION..."
              maxLength={300}
              spellCheck={false}
              autoCorrect="off"
              autoCapitalize="off"
              autoComplete="off"
              aria-label="Boolean function expression"
            />
            <button className="primary-button plot-button" onClick={() => void runAnalysis()} disabled={loading || !expression.trim()}>
              {loading ? 'PLOTTING' : 'PLOT'} <span>↗</span>
            </button>
          </div>
          <div className="input-meta"><span>{expression.length}/300 CHARACTERS</span><span>ENTER TO PLOT</span></div>
          <div className="example-row"><span className="micro-label">EXAMPLES · INSERT AT CARET</span>{EXAMPLES.map((item) => <button className="chip" key={item} onMouseDown={(event) => event.preventDefault()} onClick={() => addExample(item)}>{item}</button>)}</div>
          <div className="operator-palette"><span className="micro-label">OPERATOR PALETTE</span>{[...new Set(['(', ')', ...(activePreset?.operators.map((operator) => operator.symbols[0]).filter(Boolean) ?? [])])].map((symbol) => <button className="chip" key={symbol} onMouseDown={(event) => event.preventDefault()} onClick={() => insertAtCursor(symbol)}>{symbol}</button>)}</div>
          <div className="controls-grid">
            <div className="control-block">
              <label className="micro-label" htmlFor="preset-select">NOTATION SET</label>
              <div className="select-wrap">
                <select id="preset-select" value={presetName} onChange={(event) => setPresetName(event.target.value)}>
                  {presets.map((preset) => <option key={`${preset.name}-${customPresets.includes(preset) ? 'custom' : 'built'}`} value={preset.name}>{preset.name.toUpperCase()}{customPresets.includes(preset) ? ' · CUSTOM' : ''}</option>)}
                </select><ChevronDown size={15} />
              </div>
              <div className="control-actions">
                <button className="text-button" onClick={() => setNotationOpen((open) => !open)}><Info size={13} /> NOTATION</button>
                <button className="text-button" onClick={() => setEditorOpen(true)}><Settings2 size={13} /> EDIT PRESETS</button>
              </div>
            </div>
            <div className="control-block">
              <span className="micro-label">CIRCUIT TYPE</span>
              <div className="segmented">
                {MODES.map((item) => <button key={item.value} className={mode === item.value ? 'selected' : ''} onClick={() => setMode(item.value)}>{item.label}</button>)}
              </div>
            </div>
          </div>
          {notationOpen && activePreset && <NotationPanel preset={activePreset} onClose={() => setNotationOpen(false)} />}
          {error && <ErrorPanel error={error} expression={expression} onRetry={retry} />}
        </section>

        {!result && !error && !loading && <EmptyState />}
        {result && <div className={error ? 'results stale' : 'results'}>
          <ResultSheet result={result} activeIndex={activeIndex} onActive={setActiveIndex} copy={copy} />
        </div>}
        </>}
        {view === 'guide' && <GuideView />}
        <div hidden={view !== 'simplify'}><SimplifyView
          presetName={presetName}
          customPreset={activeCustom}
          labExpression={expression}
          onOpenLab={(value) => {
            // The result is written in textbook notation (x', +, xy), which only the universal preset is sure to read.
            setPresetName('universal'); setExpression(value); setView('lab'); void runAnalysis(value, 'universal');
          }}
        /></div>
        {view === 'reverse' && <ReverseWorkbench onOpenLab={(value) => { setExpression(value); setView('lab'); void runAnalysis(value); }} />}

        <footer className="drawing-footer">
          <div className="footer-note">ALL DIMENSIONS IN GATES. DO NOT SCALE DRAWING.</div>
          <div className="title-block drafted-box">
            <div><span>PROJECT</span><b>BOOLEAN LAB</b></div>
            <div><span>SHEET</span><b>01 / 01</b></div>
            <div><span>SCALE</span><b>1:1</b></div>
            <div><span>DWG NO</span><b>BL-001</b></div>
            <div><span>REV</span><b>A</b></div>
            <div><span>DRAWN BY</span><b>{DRAWN_BY}</b></div>
          </div>
        </footer>
      </div>

      {editorOpen && <PresetEditor
        builtIns={builtIns}
        customPresets={customPresets}
        selectedName={presetName}
        onClose={() => setEditorOpen(false)}
        onSave={(preset) => {
          updateCustomPresets([...customPresets.filter((item) => item.name !== preset.name), preset]);
          setPresetName(preset.name);
          setEditorOpen(false);
          setToast('CUSTOM PRESET SAVED');
        }}
        onDelete={(name) => {
          updateCustomPresets(customPresets.filter((item) => item.name !== name));
          if (presetName === name) setPresetName(builtIns[0]?.name ?? 'universal');
          setToast('PRESET DELETED');
        }}
      />}
      {toast && <div className="toast"><Check size={14} />{toast}</div>}
    </main>
  );
}

function ErrorPanel({ error, expression, onRetry }: { error: AppError; expression: string; onRetry: () => void }) {
  if (error.code === 'network_error') {
    return <Note hazard><div className="error-title"><AlertTriangle size={16} /> NO CONNECTION TO DRAFTING SERVER</div><p>{error.message}</p><button className="outline-button" onClick={onRetry}><RefreshCw size={13} /> RETRY</button></Note>;
  }
  const caret = error.code === 'parse_error' && error.position ? buildErrorCaret(expression, error.position) : null;
  return <Note hazard><div className="error-title"><AlertTriangle size={16} /> REVISION REQUIRED</div>
    {caret && <pre className="caret-display"><code>{caret.expression}{'\n'}{caret.caret}</code></pre>}
    <p>{error.message}</p>
  </Note>;
}

function ResultSheet({ result, activeIndex, onActive, copy, generated = false, onOpenLab, showFull = false, onShowFull }: {
  result: AnalyzeResponse; activeIndex: number | null; onActive: (index: number | null) => void;
  copy: (value: string) => Promise<void>; generated?: boolean; onOpenLab?: () => void;
  showFull?: boolean; onShowFull?: () => void;
}) {
  const longExpression = result.expression.length > 120;
  const displayedExpression = generated && longExpression && !showFull ? `${result.expression.slice(0, 120)}…` : result.expression;
  return <>
    <section className="result-section function-header drafted-box">
      <SectionTitle number="00" title={generated ? 'GENERATED FUNCTION' : 'FUNCTION DEFINITION'} />
      {generated ? <><div className="function-label generated-expression"><code>{displayedExpression}</code></div>
        <div className="section-tools"><button className="outline-button" onClick={() => void copy(result.expression)}><Copy size={13} /> COPY</button>
          {longExpression && <button className="text-button" onClick={onShowFull}>{showFull ? 'SHOW LESS' : 'SHOW FULL'}</button>}
          {onOpenLab && <button className="primary-button" onClick={onOpenLab} disabled={result.expression.length > 300} title={result.expression.length > 300 ? 'Longer than the 300-character input limit' : undefined}>OPEN IN LAB</button>}
        </div></> : <><div className="function-label">{result.function_label}</div><div className="structure-line"><span>PARSED STRUCTURE</span><code title="How the parser grouped your input">{result.structure}</code></div></>}
    </section>
    <section className="result-section drafted-box"><SectionTitle number="02" title="TRUTH TABLE" /><TruthTableView result={result} activeIndex={activeIndex} onActive={onActive} onCopy={() => void copy(truthTableToTSV(result))} /></section>
    <section className="result-section drafted-box"><SectionTitle number="03" title="CANONICAL FORMS" /><FormsView result={result} activeIndex={activeIndex} onActive={onActive} onCopy={copy} /></section>
    <section className="result-section drafted-box"><SectionTitle number="04" title="KARNAUGH MAP" />{result.kmap ? <KMapView result={result} activeIndex={activeIndex} onActive={onActive} /> : <Note>{result.warnings.length ? result.warnings.join(' · ') : 'KARNAUGH MAP UNAVAILABLE FOR THIS FUNCTION.'}</Note>}</section>
    <section className="result-section drafted-box"><SectionTitle number="05" title="LOGIC CIRCUIT" />{result.circuit ? <CircuitView circuit={result.circuit} variables={result.variables} /> : <Note>{result.warnings.length ? result.warnings.join(' · ') : 'CIRCUIT UNAVAILABLE.'}</Note>}</section>
    {result.warnings.length > 0 && <section className="result-section drafted-box"><SectionTitle number="06" title="WARNINGS" /><Note>{result.warnings.map((warning, index) => <div key={`${index}-${warning}`}>— {warning}</div>)}</Note></section>}
  </>;
}

function EmptyState() {
  return <div className="empty-state">
    <svg viewBox="0 0 680 210" role="img" aria-label="Blueprint placeholder logic diagram">
      <g fill="none" stroke="currentColor" strokeWidth="1">
        <path d="M50 45 H180 V85 H280 M50 165 H180 V125 H280 M280 85 H420 V105 H570" strokeDasharray="5 5" />
        <rect x="280" y="65" width="95" height="80" />
        <path d="M280 65 Q330 105 280 145 M375 65 Q420 105 375 145" />
        <circle cx="50" cy="45" r="5" /><circle cx="50" cy="165" r="5" /><circle cx="570" cy="105" r="5" />
        <path d="M570 105 l-12 -6 v12 z" fill="currentColor" />
        <path d="M20 20 H660 M20 190 H660" strokeDasharray="2 8" opacity=".45" />
      </g>
      <g fill="currentColor" fontFamily="monospace" fontSize="11"><text x="35" y="32">INPUT A</text><text x="35" y="185">INPUT B</text><text x="318" y="109">GATE</text><text x="585" y="109">F</text></g>
    </svg>
    <div className="empty-title">AWAITING INPUT.</div>
    <p>TYPE A FUNCTION, E.G. <code>x'y + xy'</code></p>
    <span className="empty-coordinates">FIG. 01 · LOGIC SYSTEM STANDBY</span>
  </div>;
}

function NotationPanel({ preset, onClose }: { preset: Preset; onClose: () => void }) {
  return <div className="notation-panel drafted-box">
    <div className="panel-heading"><strong>ACTIVE NOTATION / {preset.name.toUpperCase()}</strong><button className="icon-button" onClick={onClose} aria-label="Close notation"><X size={15} /></button></div>
    {preset.description && <p className="muted">{preset.description}</p>}
    <div className="table-scroll"><table className="notation-table"><thead><tr><th>OPERATOR</th><th>FIXITY</th><th>SYMBOLS</th><th>PREC.</th><th>TABLE</th></tr></thead>
      <tbody>{preset.operators.map((op, i) => <tr key={`${op.name}-${op.fixity}-${i}`}><td>{op.name}</td><td>{op.fixity}</td><td>{op.symbols.join('  ')}</td><td>{op.precedence}</td><td>{op.table.join('')}</td></tr>)}</tbody>
    </table></div>
    <p className="muted">IMPLICIT OPERATOR: {preset.implicit ?? 'NONE'}</p>
  </div>;
}

function TruthTableView({ result, activeIndex, onActive, onCopy }: {
  result: AnalyzeResponse; activeIndex: number | null; onActive: (index: number | null) => void; onCopy: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowHeight = 35;
  const viewportHeight = expanded ? Math.min(window.innerHeight * 0.75, 720) : 390;
  const overscan = 7;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const visibleCount = Math.ceil(viewportHeight / rowHeight) + overscan * 2;
  const end = Math.min(result.truth_table.rows.length, start + visibleCount);
  const visibleRows = result.truth_table.rows.slice(start, end);
  const columnCount = result.truth_table.variables.length + 2;
  useEffect(() => {
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [result.expression, result.truth_table.rows.length]);
  useEffect(() => {
    if (activeIndex !== null && (activeIndex < start || activeIndex >= end)) {
      const nextTop = Math.max(0, activeIndex * rowHeight);
      if (scrollRef.current) scrollRef.current.scrollTop = nextTop;
      setScrollTop(nextTop);
    }
  }, [activeIndex, start, end, rowHeight]);
  return <div>
    <div className="section-tools"><span>{result.truth_table.rows.length} ROWS · {result.variables.length} VARIABLES</span>
      <div><button className="outline-button" onClick={onCopy}><Copy size={13} /> COPY TSV</button>
        <button className="outline-button" onClick={() => downloadText(truthTableToCSV(result), 'boolean-truth-table.csv', 'text/csv')}><Download size={13} /> CSV</button></div>
    </div>
    <div ref={scrollRef} className={`truth-scroll ${expanded ? 'expanded' : ''}`} style={{ height: viewportHeight }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
      <table className="truth-table"><thead><tr><th>#</th>{result.truth_table.variables.map((variable) => <th key={variable}>{variable}</th>)}<th>F</th></tr></thead>
        <tbody>
          {start > 0 && <tr aria-hidden="true"><td colSpan={columnCount} style={{ height: start * rowHeight, padding: 0, border: 0 }} /></tr>}
          {visibleRows.map((row) => <tr key={row.index} className={`${activeIndex === row.index ? 'active-row' : ''} ${row.output === 1 ? 'output-one' : ''}`}
            onMouseEnter={() => onActive(row.index)} onMouseLeave={() => onActive(null)}
            onFocus={() => onActive(row.index)} onBlur={() => onActive(null)} tabIndex={0}>
            <td>{row.index}</td>{row.inputs.map((bit, i) => <td key={`${row.index}-${i}`}>{bit}</td>)}<td className={row.output ? 'one' : ''}>{row.output}</td>
          </tr>)}
          {end < result.truth_table.rows.length && <tr aria-hidden="true"><td colSpan={columnCount} style={{ height: (result.truth_table.rows.length - end) * rowHeight, padding: 0, border: 0 }} /></tr>}
        </tbody>
      </table>
    </div>
    {result.truth_table.rows.length > 16 && <button className="text-button expand-table" onClick={() => setExpanded((v) => !v)}>{expanded ? 'COLLAPSE TABLE' : 'EXPAND TABLE'} <ChevronDown size={13} /></button>}
  </div>;
}

function FormsView({ result, activeIndex, onActive, onCopy }: {
  result: AnalyzeResponse; activeIndex: number | null; onActive: (index: number | null) => void; onCopy: (text: string) => Promise<void>;
}) {
  const cards = [
    { title: 'SUM OF MINTERMS', formula: result.forms.sigma.text, terms: null },
    { title: 'PRODUCT OF MAXTERMS', formula: result.forms.pi.text, terms: null },
    { title: 'SUM OF PRODUCTS', formula: result.forms.sop.text, terms: result.forms.sop.terms },
    { title: 'PRODUCT OF SUMS', formula: result.forms.pos.text, terms: result.forms.pos.terms },
  ];
  return <div className="forms-grid">{cards.map((card) => <article className="form-card drafted-box" key={card.title}>
    <div className="form-card-top"><span>{card.title}</span>
      {card.title === (result.forms.shorter === 'sop' ? 'SUM OF PRODUCTS' : 'PRODUCT OF SUMS') && <span className="shorter-badge" title="Fewer terms to write. This is not minimisation.">SHORTER</span>}
      <button className="icon-button" onClick={() => void onCopy(card.formula)} aria-label={`Copy ${card.title}`}><Copy size={14} /></button>
    </div>
    <div className="form-expression">{card.formula}</div>
    {card.terms && card.terms.length > 0 && <div className="term-list">{card.terms.map((term) =>
      <button key={term.index} className={`term ${activeIndex === term.index ? 'active' : ''}`} onMouseEnter={() => onActive(term.index)} onMouseLeave={() => onActive(null)} onFocus={() => onActive(term.index)} onBlur={() => onActive(null)}>{term.term}<small>m{term.index} · {term.bits}</small></button>
    )}</div>}
  </article>)}</div>;
}

function KMapView({ result, activeIndex, onActive }: {
  result: AnalyzeResponse; activeIndex: number | null; onActive: (index: number | null) => void;
}) {
  const map = result.kmap!;
  return <div className="kmap-wrap">
    <table className="kmap-table"><thead><tr><th className="corner-cell">{map.corner}</th>{map.col_labels.map((label, i) => <th key={`${label}-${i}`}>{label}</th>)}</tr></thead>
      <tbody>{map.cells.map((row, rowIndex) => <tr key={rowIndex}><th>{map.row_labels[rowIndex]}</th>{row.map((cell) =>
        <td key={cell.index} className={`${cell.value ? 'k-one' : ''} ${activeIndex === cell.index ? 'highlight' : ''}`}
          onMouseEnter={() => onActive(cell.index)} onMouseLeave={() => onActive(null)} tabIndex={0}
          onFocus={() => onActive(cell.index)} onBlur={() => onActive(null)}>
          <strong>{cell.value}</strong><small>{cell.index}</small>
        </td>)}</tr>)}</tbody>
    </table>
    <div className="kmap-caption"><span>GRAY-CODE ORDER</span><span>EDGES WRAP AROUND ↔</span></div>
  </div>;
}

function CircuitView({ circuit, variables }: { circuit: Circuit; variables: string[] }) {
  const [inputs, setInputs] = useState<Record<string, Bit>>(() => Object.fromEntries(variables.map((v) => [v, 0 as Bit])));
  const [hovered, setHovered] = useState<string | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const evaluation = useMemo(() => evaluateCircuit(circuit, inputs), [circuit, inputs]);
  const cone = useMemo(() => hovered ? getUpstreamCone(circuit, hovered) : null, [circuit, hovered]);
  const COL_W = 150;
  const ROW_H = 76;
  const MARGIN_X = 55;
  const MARGIN_Y = 55;
  const width = Math.max(560, MARGIN_X * 2 + (circuit.cols - 1) * COL_W + 100);
  const height = Math.max(180, MARGIN_Y * 2 + (circuit.rows - 1) * ROW_H + 50);
  const nodes = new Map(circuit.nodes.map((node) => [node.id, node]));
  const fanout = new Map<string, number>();
  circuit.edges.forEach((edge) => fanout.set(edge.source, (fanout.get(edge.source) ?? 0) + 1));
  const wirePalette = ['#DCEBFF', '#B9E7FF', '#D9D0FF', '#F2D6B3', '#BFE9D2', '#E8C8DF', '#C8D9A9', '#F0E5A8'];
  const sourceVariable = (id: string, visited = new Set<string>()): string => {
    if (visited.has(id)) return '';
    visited.add(id);
    const current = nodes.get(id);
    if (!current) return '';
    if (current.kind === 'input') return current.label;
    for (const inputId of current.inputs) {
      const found = sourceVariable(inputId, visited);
      if (found) return found;
    }
    return '';
  };
  const wireColor = (id: string) => {
    const variable = sourceVariable(id);
    const index = Math.max(0, variables.indexOf(variable));
    return wirePalette[index % wirePalette.length];
  };
  const positions = (node: CircuitNode) => ({
    x: MARGIN_X + node.col * COL_W,
    y: MARGIN_Y + node.row * ROW_H,
  });

  const wirePath = (source: CircuitNode, target: CircuitNode, edgeIndex: number, edge: Circuit['edges'][number]) => {
    const a = positions(source);
    const b = positions(target);
    const sx = a.x + (source.kind === 'input' || source.kind === 'const' ? 14 : 34);
    const sy = a.y;
    const tx = b.x - 34;
    const ty = b.y + (edge.ports > 1 ? ((edge.port / Math.max(1, edge.ports - 1)) - 0.5) * 28 : 0);
    const channel = sx + (tx - sx) * 0.5 + ((edgeIndex % 7) - 3) * 5;
    return `M ${sx} ${sy} H ${channel} V ${ty} H ${tx}`;
  };

  const exportSvg = () => {
    if (!svgRef.current) return;
    const clone = svgRef.current.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(width));
    clone.setAttribute('height', String(height));
    const source = new XMLSerializer().serializeToString(clone);
    downloadText(source, 'boolean-circuit.svg', 'image/svg+xml');
  };

  const exportPng = () => {
    if (!svgRef.current) return;
    const clone = svgRef.current.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(width * 2));
    clone.setAttribute('height', String(height * 2));
    clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const source = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = width * 2;
      canvas.height = height * 2;
      const context = canvas.getContext('2d');
      if (context) {
        context.fillStyle = '#082F73';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((png) => {
          if (png) {
            const pngUrl = URL.createObjectURL(png);
            const anchor = document.createElement('a');
            anchor.href = pngUrl;
            anchor.download = 'boolean-circuit.png';
            anchor.click();
            URL.revokeObjectURL(pngUrl);
          }
          URL.revokeObjectURL(url);
        }, 'image/png');
      } else URL.revokeObjectURL(url);
    };
    image.onerror = () => URL.revokeObjectURL(url);
    image.src = url;
  };

  return <div className="circuit-container drafted-box">
    <div className="circuit-toolbar"><span>{circuit.gate_count} GATES · {circuit.nodes.length} NODES</span>
      <div><button className="outline-button" onClick={() => setFitKey((k) => k + 1)}><Maximize2 size={13} /> FIT</button>
        <button className="outline-button" onClick={exportSvg}><Download size={13} /> EXPORT SVG</button>
        <button className="outline-button" onClick={exportPng}><ArrowDownToLine size={13} /> EXPORT PNG</button></div>
    </div>
    <TransformWrapper key={fitKey} initialScale={1} minScale={0.35} maxScale={2.5} centerOnInit wheel={{ step: 0.08 }} doubleClick={{ disabled: true }}>
      <TransformComponent wrapperClass="circuit-pan" contentClass="circuit-content">
        <svg ref={svgRef} className="circuit-svg" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Interactive logic circuit">
          <defs><pattern id="circuit-grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="rgba(255,255,255,.10)" strokeWidth=".6" /></pattern></defs>
          <rect width={width} height={height} fill="url(#circuit-grid)" />
          {circuit.edges.map((edge, i) => {
            const source = nodes.get(edge.source);
            const target = nodes.get(edge.target);
            if (!source || !target) return null;
            const sourceValue = evaluation.values.get(source.id) ?? 0;
            const highlighted = !cone || (cone.has(source.id) && cone.has(target.id));
            return <g key={`${edge.source}-${edge.target}-${edge.port}`} opacity={highlighted ? 1 : 0.18}>
              <path d={wirePath(source, target, i, edge)} className={`wire ${sourceValue ? 'wire-one' : ''}`} style={{ stroke: sourceValue ? undefined : wireColor(source.id) }} />
              {fanout.get(source.id)! > 1 && edge.port === 0 && <circle cx={positions(source).x + 43} cy={positions(source).y} r="3" className="junction" />}
            </g>;
          })}
          {circuit.nodes.map((node) => {
            const p = positions(node);
            const value = evaluation.values.get(node.id) ?? 0;
            const isGate = node.kind === 'gate';
            const active = !cone || cone.has(node.id);
            return <g key={node.id} transform={`translate(${p.x},${p.y})`} opacity={active ? 1 : 0.25}
              onMouseEnter={() => isGate && setHovered(node.id)} onMouseLeave={() => setHovered(null)}
              onFocus={() => isGate && setHovered(node.id)} onBlur={() => setHovered(null)} tabIndex={isGate ? 0 : undefined}
              className={isGate ? 'gate-node' : ''}>
              {node.kind === 'input' || node.kind === 'const' ? <>
                <circle r="13" className={`terminal ${value ? 'terminal-one' : ''}`} />
                <text y="4" textAnchor="middle" className="terminal-text">{node.kind === 'input' ? node.label : node.label}</text>
                <text x="-19" y="-19" textAnchor="end" className="node-caption">{node.label}</text>
              </> : node.kind === 'output' ? <>
                <path d="M-26 0 H25 M14 -8 L26 0 L14 8" className={`output-arrow ${value ? 'wire-one' : ''}`} />
                <text x="34" y="5" className="output-label">F = {value}</text>
              </> : <GateGraphic node={node} value={value} />}
            </g>;
          })}
        </svg>
      </TransformComponent>
    </TransformWrapper>
    {hovered && nodes.get(hovered)?.table && <div className="gate-tooltip"><strong>{nodes.get(hovered)?.gate}</strong><span>TRUTH TABLE</span><code>{nodes.get(hovered)?.table?.join(' · ')}</code></div>}
    <div className="switch-panel"><div className="switch-title">TEST INPUTS <span>LIVE CIRCUIT EVALUATION</span></div>
      <div className="switches">{variables.map((variable) => <button key={variable} className={`switch ${inputs[variable] ? 'switch-on' : ''}`} onClick={() => setInputs((current) => ({ ...current, [variable]: current[variable] ? 0 : 1 }))} aria-pressed={Boolean(inputs[variable])}>
        <span className="switch-track"><i /></span><b>{variable}</b><small>{inputs[variable]}</small>
      </button>)}</div>
      <div className="live-output"><span>FUNCTION OUTPUT</span><strong className={evaluation.output ? 'output-active' : ''}>{evaluation.output}</strong></div>
    </div>
  </div>;
}

function GateGraphic({ node, value }: { node: CircuitNode; value: Bit }) {
  const shape: GateShape = node.shape ?? 'box';
  const cls = `gate-outline ${value ? 'gate-one' : ''}`;
  const text = node.gate ?? node.label;
  if (shape === 'not') {
    return <><path d="M-30 -22 L22 0 L-30 22 Z" className={cls} /><circle cx="28" r="6" className={`gate-bubble ${value ? 'gate-one' : ''}`} /><text x="-5" y="4" textAnchor="middle" className="gate-label">{text}</text></>;
  }
  if (shape === 'and' || shape === 'nand') {
    return <><path d="M-31 -22 H-8 A22 22 0 0 1 -8 22 H-31 Z" className={cls} />{shape === 'nand' && <circle cx="36" r="6" className={`gate-bubble ${value ? 'gate-one' : ''}`} />}<text x="-8" y="4" textAnchor="middle" className="gate-label">{text}</text></>;
  }
  if (shape === 'or' || shape === 'nor' || shape === 'xor' || shape === 'xnor') {
    const gatePath = 'M-32 -22 C-17 -20 8 -11 32 0 C8 11 -17 20 -32 22 C-21 10 -21 -10 -32 -22 Z';
    return <><path d={gatePath} className={cls} />
      {shape === 'xor' || shape === 'xnor' ? <path d="M-40 -22 C-29 -10 -29 10 -40 22" className={cls} /> : null}
      {shape === 'nor' || shape === 'xnor' ? <circle cx="39" r="6" className={`gate-bubble ${value ? 'gate-one' : ''}`} /> : null}
      <text x="-1" y="4" textAnchor="middle" className="gate-label gate-label-small">{text}</text></>;
  }
  return <><rect x="-34" y="-22" width="68" height="44" rx="2" className={cls} /><text y="4" textAnchor="middle" className="gate-label">{text}</text></>;
}


function GuideView() {
  return <section className="guide-view drafted-box">
    <SectionTitle number="G1" title="BOOLEAN ALGEBRA / FIELD GUIDE" />
    <p className="guide-lead">A compact reference for reading, constructing and testing Boolean functions.</p>
    <div className="guide-grid">
      <article className="guide-card drafted-box"><h3>01 — THE TWO-STATE SYSTEM</h3><p>Boolean algebra operates on two values: 0 (false / LOW) and 1 (true / HIGH). A Boolean function maps one or more binary inputs to exactly one binary output.</p><code>F(x, y) → {`{0, 1}`}</code></article>
      <article className="guide-card drafted-box"><h3>02 — CORE OPERATORS</h3><dl><dt>NOT · x'</dt><dd>Inverts the input: 0 becomes 1; 1 becomes 0.</dd><dt>AND · x * y</dt><dd>Returns 1 only when every input is 1.</dd><dt>OR · x + y</dt><dd>Returns 1 when at least one input is 1.</dd><dt>XOR · x ^ y</dt><dd>Returns 1 when the two inputs differ.</dd><dt>NAND / NOR</dt><dd>Inverted AND / OR. Each is a universal gate.</dd></dl></article>
      <article className="guide-card drafted-box"><h3>03 — PRECEDENCE</h3><p>Unless parentheses change the order, NOT binds before AND, AND before XOR, XOR before OR, then implication and equivalence. Use parentheses when clarity matters.</p><code>NOT → AND → XOR → OR → IMP → EQV</code></article>
      <article className="guide-card drafted-box"><h3>04 — WHAT THE LAB GENERATES</h3><ul><li><b>Truth table:</b> every possible input combination and its output.</li><li><b>Canonical forms:</b> minterms, maxterms, SOP and POS.</li><li><b>Karnaugh map:</b> Gray-code arrangement for visual grouping; edges wrap.</li><li><b>Logic circuit:</b> gates and wires representing the function.</li><li><b>Live test:</b> toggle inputs and observe signal propagation.</li></ul></article>
      <article className="guide-card drafted-box"><h3>05 — HOW TO USE THE LAB</h3><ol><li>Choose a notation set.</li><li>Enter a function or load an example.</li><li>Press Enter or PLOT; analysis also runs after a short pause.</li><li>Change circuit type to inspect the typed, SOP or POS implementation.</li><li>Hover rows, terms and map cells to cross-highlight matching minterm indices.</li><li>Toggle circuit inputs, inspect gate truth tables, then export SVG or PNG.</li></ol></article>
      <article className="guide-card drafted-box"><h3>06 — READING THE OUTPUT</h3><p>Σm lists row indices where F = 1. ΠM lists row indices where F = 0. SOP is an OR of AND terms; POS is an AND of OR terms. “SHORTER” compares the number of canonical terms; it does not mean minimised.</p></article>
    </div>
    <Note>THE SERVER IS THE SOURCE OF TRUTH FOR PARSING, TRUTH TABLES, CANONICAL FORMS AND CIRCUIT TOPOLOGY. THIS GUIDE DESCRIBES THE FRONTEND'S CURRENT NOTATION AND VISUAL OUTPUT.</Note>
  </section>;
}

function ReverseWorkbench({ onOpenLab }: { onOpenLab: (expression: string) => void }) {
  const [variableCount, setVariableCount] = useState(3);
  const [outputs, setOutputs] = useState<Record<number, Bit>>({});
  const [functionForm, setFunctionForm] = useState<'auto' | 'sop' | 'pos'>('auto');
  const [circuitMode, setCircuitMode] = useState<CircuitMode>('expression');
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<AppError | null>(null);
  const [loading, setLoading] = useState(false);
  const [stale, setStale] = useState(false);
  const [showFull, setShowFull] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const rowCount = 2 ** variableCount;
  const variables = Array.from({ length: variableCount }, (_, i) => String.fromCharCode(97 + i));
  const rows = Array.from({ length: rowCount }, (_, index) => ({ index, bits: index.toString(2).padStart(variableCount, '0').split('').map(Number), output: outputs[index] ?? 0 }));
  const reverseRowHeight = 35;
  const reverseViewport = 520;
  const reverseStart = Math.max(0, Math.floor(scrollTop / reverseRowHeight) - 6);
  const reverseEnd = Math.min(rowCount, reverseStart + Math.ceil(reverseViewport / reverseRowHeight) + 12);
  const ones = rows.filter((row) => row.output === 1).map((row) => row.index);
  const zeros = rows.filter((row) => row.output === 0).map((row) => row.index);
  const candidate = ones.length <= zeros.length ? `Σm(${ones.join(', ')})` : `ΠM(${zeros.join(', ')})`;

  useEffect(() => () => abortRef.current?.abort(), []);
  const generate = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const data = await api.synthesize({ outputs: denseOutputs(outputs, variableCount), function_form: functionForm, circuit_mode: circuitMode }, controller.signal);
      if (!controller.signal.aborted) { setResult(data); setStale(false); setShowFull(false); }
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof ApiClientError
        ? { code: caught.code, message: caught.message, position: caught.position }
        : { code: 'network_error', message: 'NO CONNECTION TO DRAFTING SERVER' });
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  const updateOutputs = (next: Record<number, Bit>) => { abortRef.current?.abort(); setLoading(false); setOutputs(next); if (result) setStale(true); };
  const changeFunctionForm = (value: 'auto' | 'sop' | 'pos') => { abortRef.current?.abort(); setLoading(false); setFunctionForm(value); if (result) setStale(true); };
  const changeCircuitMode = (value: CircuitMode) => { abortRef.current?.abort(); setLoading(false); setCircuitMode(value); if (result) setStale(true); };

  return <section className="reverse-view drafted-box">
    <SectionTitle number="R1" title="TRUTH TABLE → BOOLEAN FUNCTION" />
    <p className="guide-lead">Set each output bit, then generate its Boolean function and analysis.</p>
    <div className="reverse-controls drafted-box">
      <label>VARIABLE COUNT <select value={variableCount} onChange={(event) => {
        abortRef.current?.abort(); setVariableCount(Number(event.target.value)); setOutputs({});
        setResult(null); setError(null); setStale(false); setLoading(false); setScrollTop(0);
      }}>{Array.from({ length: 12 }, (_, i) => i + 1).map((count) => <option key={count} value={count}>{count} VARIABLES / {2 ** count} ROWS</option>)}</select></label>
      <div className="control-block"><span className="micro-label">FUNCTION FORM</span><div className="segmented">
        {([{ value: 'auto', label: 'AUTO' }, { value: 'sop', label: 'SUM OF PRODUCTS' }, { value: 'pos', label: 'PRODUCT OF SUMS' }] as const).map((item) =>
          <button key={item.value} className={functionForm === item.value ? 'selected' : ''} onClick={() => changeFunctionForm(item.value)}>{item.label}</button>)}
      </div></div>
      <div className="control-block"><span className="micro-label">CIRCUIT TYPE</span><div className="segmented">
        {MODES.map((item, index) => <button key={item.value} className={circuitMode === item.value ? 'selected' : ''} onClick={() => changeCircuitMode(item.value)}>{index === 0 ? 'AS WRITTEN' : item.label}</button>)}
      </div></div>
      <button className="primary-button" onClick={() => void generate()} disabled={loading}>{loading ? 'PLOTTING...' : 'GENERATE FUNCTION'} <span>↗</span></button>
      <button className="outline-button" onClick={() => updateOutputs({})}>RESET OUTPUTS</button>
      <button className="outline-button" onClick={() => updateOutputs(Object.fromEntries(rows.map((row) => [row.index, 1 as Bit])) as Record<number, Bit>)}>SET ALL 1</button>
      <button className="outline-button" onClick={() => updateOutputs(Object.fromEntries(rows.map((row) => [row.index, 0 as Bit])) as Record<number, Bit>)}>SET ALL 0</button>
    </div>
    <div className="reverse-table-wrap drafted-box" onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}><table className="truth-table reverse-table"><thead><tr><th>#</th>{variables.map((v) => <th key={v}>{v}</th>)}<th>F</th></tr></thead><tbody>{reverseStart > 0 && <tr aria-hidden="true"><td colSpan={variableCount + 2} style={{ height: reverseStart * reverseRowHeight, padding: 0, border: 0 }} /></tr>}{rows.slice(reverseStart, reverseEnd).map((row) => <tr key={row.index}><td>{row.index}</td>{row.bits.map((bit, i) => <td key={i}>{bit}</td>)}<td><button className={`bit-toggle ${row.output ? 'selected' : ''}`} aria-label={`Set output for row ${row.index} to ${row.output ? 0 : 1}`} aria-pressed={Boolean(row.output)} onClick={() => updateOutputs({ ...outputs, [row.index]: row.output ? 0 : 1 })}>{row.output}</button></td></tr>)}{reverseEnd < rowCount && <tr aria-hidden="true"><td colSpan={variableCount + 2} style={{ height: (rowCount - reverseEnd) * reverseRowHeight, padding: 0, border: 0 }} /></tr>}</tbody></table></div>
    <div className="reverse-preview drafted-box"><span className="micro-label">LIVE PREVIEW</span><code>Σm({ones.join(', ')})</code><code>ΠM({zeros.join(', ')})</code><p>{ones.length} minterms · {zeros.length} maxterms · {rowCount} combinations · shorter index list: {candidate}</p></div>
    {error && <ErrorPanel error={error} expression="" onRetry={() => void generate()} />}
    {result && <div className={stale ? 'results stale' : 'results'}>
      {stale && <Note>TABLE CHANGED. GENERATE AGAIN.</Note>}
      <ResultSheet result={result} activeIndex={null} onActive={() => undefined} copy={async (value) => { await copyText(value); }} generated onOpenLab={() => onOpenLab(result.expression)} showFull={showFull} onShowFull={() => setShowFull((value) => !value)} />
    </div>}
  </section>;
}

function PresetEditor({ builtIns, customPresets, selectedName, onClose, onSave, onDelete }: {
  builtIns: Preset[]; customPresets: Preset[]; selectedName: string;
  onClose: () => void; onSave: (preset: Preset) => void; onDelete: (name: string) => void;
}) {
  const blank: Preset = { name: 'my-preset', description: '', implicit: 'AND', operators: [
    { name: 'NOT', fixity: 'postfix', symbols: ["'"], precedence: 60, table: [1, 0], shape: 'not' },
    { name: 'AND', fixity: 'infix', symbols: ['*'], precedence: 50, assoc: 'left', table: [0, 0, 0, 1], nary: true, shape: 'and' },
    { name: 'OR', fixity: 'infix', symbols: ['+'], precedence: 30, assoc: 'left', table: [0, 1, 1, 1], nary: true, shape: 'or' },
  ] };
  const [draft, setDraft] = useState<Preset>(() => customPresets.find((p) => p.name === selectedName) ?? blank);
  const [selectedSource, setSelectedSource] = useState(selectedName);
  const [validation, setValidation] = useState<{ valid: boolean; message: string } | null>(null);
  const [validating, setValidating] = useState(false);
  const [importText, setImportText] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [tab, setTab] = useState<'edit' | 'json'>('edit');
  const validationTimer = useRef<number | null>(null);
  const abort = useRef<AbortController | null>(null);

  const validate = useCallback((preset: Preset) => {
    if (validationTimer.current !== null) window.clearTimeout(validationTimer.current);
    validationTimer.current = window.setTimeout(async () => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setValidating(true);
      try {
        await api.validatePreset(preset, controller.signal);
        if (!controller.signal.aborted) setValidation({ valid: true, message: 'PRESET VALIDATED BY SERVER' });
      } catch (error) {
        if (controller.signal.aborted) return;
        setValidation({ valid: false, message: error instanceof Error ? error.message : 'VALIDATION FAILED' });
      } finally {
        if (!controller.signal.aborted) setValidating(false);
      }
    }, 450);
  }, []);

  useEffect(() => {
    validate(draft);
    return () => { if (validationTimer.current !== null) window.clearTimeout(validationTimer.current); abort.current?.abort(); };
  }, [draft, validate]);

  const setOperator = (index: number, patch: Partial<Operator>) => {
    setDraft((current) => ({ ...current, operators: current.operators.map((op, i) => i === index ? { ...op, ...patch } : op) }));
  };
  const loadPreset = (name: string) => {
    const source = customPresets.find((p) => p.name === name) ?? builtIns.find((p) => p.name === name);
    if (!source) return;
    setSelectedSource(name);
    setDraft({ ...source, name: customPresets.some((p) => p.name === name) ? source.name : `${source.name}-copy`, operators: source.operators.map((op) => ({ ...op, symbols: [...op.symbols], table: [...op.table] })) });
    setValidation(null);
  };
  const addOperator = () => setDraft((current) => ({ ...current, operators: [...current.operators, { name: 'NEW_OP', fixity: 'infix', symbols: ['@'], precedence: 25, assoc: 'left', table: [0, 0, 0, 1], shape: 'box' }] }));
  const removeOperator = (index: number) => setDraft((current) => ({ ...current, operators: current.operators.filter((_, i) => i !== index) }));
  const toggleBit = (index: number, bitIndex: number) => {
    const op = draft.operators[index];
    if (!op) return;
    const table = [...op.table];
    table[bitIndex] = table[bitIndex] === 1 ? 0 : 1;
    setOperator(index, { table: table as Bit[] });
  };
  const exportJson = () => downloadText(JSON.stringify(draft, null, 2), `${draft.name}.json`, 'application/json');
  const importJson = () => {
    try {
      const parsed: unknown = JSON.parse(importText);
      if (!parsed || typeof parsed !== 'object' || !('operators' in parsed) || !Array.isArray((parsed as Preset).operators)) throw new Error('JSON must contain a preset with an operators array.');
      setDraft(parsed as Preset);
      setShowImport(false);
      setValidation(null);
    } catch (error) { setValidation({ valid: false, message: error instanceof Error ? error.message : 'INVALID JSON' }); }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="preset-modal" role="dialog" aria-modal="true" aria-labelledby="preset-editor-title">
      <header className="modal-header"><div><span className="micro-label">CONFIGURATION MODULE / 01</span><h2 id="preset-editor-title">CUSTOM PRESET EDITOR</h2></div><button className="icon-button" onClick={onClose} aria-label="Close editor"><X /></button></header>
      <div className="editor-toolbar"><div className="select-wrap"><select value={selectedSource} onChange={(e) => loadPreset(e.target.value)}><optgroup label="BUILT-IN">{builtIns.map((p) => <option key={p.name}>{p.name}</option>)}</optgroup><optgroup label="CUSTOM">{customPresets.map((p) => <option key={p.name}>{p.name}</option>)}</optgroup></select><ChevronDown size={14} /></div>
        <button className="outline-button" onClick={() => { setDraft(blank); setSelectedSource('new'); }}><Plus size={13} /> NEW</button>
        <button className="outline-button" onClick={() => setShowImport((v) => !v)}><Upload size={13} /> IMPORT JSON</button>
        <button className="outline-button" onClick={exportJson}><FileJson size={13} /> EXPORT</button>
      </div>
      {showImport && <div className="import-box"><textarea value={importText} onChange={(e) => setImportText(e.target.value)} placeholder="PASTE PRESET JSON..." /><button className="primary-button" onClick={importJson}>IMPORT</button></div>}
      <div className="editor-tabs"><button className={tab === 'edit' ? 'active' : ''} onClick={() => setTab('edit')}>OPERATOR FORM</button><button className={tab === 'json' ? 'active' : ''} onClick={() => setTab('json')}>JSON PREVIEW</button></div>
      {tab === 'edit' ? <div className="editor-body">
        <div className="editor-meta-grid">
          <label>PRESET NAME<input value={draft.name} maxLength={32} onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))} /></label>
          <label>IMPLICIT OPERATOR<input value={draft.implicit ?? ''} onChange={(e) => setDraft((p) => ({ ...p, implicit: e.target.value || null }))} placeholder="NONE" /></label>
          <label className="wide-label">DESCRIPTION<input value={draft.description ?? ''} onChange={(e) => setDraft((p) => ({ ...p, description: e.target.value }))} /></label>
        </div>
        <div className="operators-heading"><strong>OPERATORS</strong><button className="text-button" onClick={addOperator}><Plus size={13} /> ADD OPERATOR</button></div>
        {draft.operators.map((op, index) => <article className="operator-editor" key={`${index}-${op.name}`}>
          <div className="operator-head"><strong>{String(index + 1).padStart(2, '0')} / {op.name}</strong><button className="icon-button danger-hover" onClick={() => removeOperator(index)} aria-label={`Delete ${op.name}`}><Trash2 size={14} /></button></div>
          <div className="operator-fields">
            <label>NAME<input value={op.name} onChange={(e) => setOperator(index, { name: e.target.value })} /></label>
            <label>FIXITY<select value={op.fixity} onChange={(e) => { const fixity = e.target.value as Operator['fixity']; setOperator(index, { fixity, table: fixity === 'infix' ? [0,0,0,1] : [1,0], assoc: fixity === 'infix' ? 'left' : undefined }); }}><option value="prefix">PREFIX</option><option value="postfix">POSTFIX</option><option value="infix">INFIX</option></select></label>
            <label>SYMBOLS<input value={op.symbols.join(', ')} onChange={(e) => setOperator(index, { symbols: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} /></label>
            <label>PRECEDENCE<input type="number" min="1" max="99" value={op.precedence} onChange={(e) => setOperator(index, { precedence: Number(e.target.value) })} /></label>
            {op.fixity === 'infix' && <label>ASSOCIATIVITY<select value={op.assoc ?? 'left'} onChange={(e) => setOperator(index, { assoc: e.target.value as Operator['assoc'] })}><option value="left">LEFT</option><option value="right">RIGHT</option></select></label>}
            <label>SHAPE<select value={op.shape ?? 'box'} onChange={(e) => setOperator(index, { shape: e.target.value as GateShape })}>{['and','or','not','xor','nand','nor','xnor','box'].map((s) => <option key={s} value={s}>{s.toUpperCase()}</option>)}</select></label>
          </div>
          <div className="truth-bits"><span>OUTPUT TABLE</span>{op.table.map((bit, bitIndex) => <button key={bitIndex} className={bit ? 'bit-active' : ''} onClick={() => toggleBit(index, bitIndex)}>{bit}</button>)}
            {op.fixity === 'infix' && <label className="nary-check"><input type="checkbox" checked={Boolean(op.nary)} onChange={(e) => setOperator(index, { nary: e.target.checked })} /> N-ARY</label>}
          </div>
        </article>)}
      </div> : <pre className="json-preview">{JSON.stringify(draft, null, 2)}</pre>}
      <footer className="modal-footer">
        <div className={`validation-state ${validation?.valid ? 'valid' : validation ? 'invalid' : ''}`}>{validating ? 'VALIDATING…' : validation?.message ?? 'WAITING FOR VALIDATION'}</div>
        {customPresets.some((p) => p.name === draft.name) && <button className="outline-button" onClick={() => onDelete(draft.name)}><Trash2 size={13} /> DELETE</button>}
        <button className="primary-button" disabled={!validation?.valid || validating || !draft.name.trim()} onClick={() => onSave(draft)}>SAVE PRESET</button>
      </footer>
    </section>
  </div>;
}

export default App;
