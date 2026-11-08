import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Check, ChevronDown, Copy, Download, Loader2 } from 'lucide-react';
import type { ApiErrorCode, Preset, SimplifyResponse, SimplifyStep } from '../api/types';
import { api, ApiClientError } from '../api/client';
import { buildErrorCaret } from '../utils/error-caret';
import { copyText, downloadText } from '../utils/formatters';
import { cooldownLabel, splitHighlight, stepsToText, textBeforeStep } from '../utils/simplify-format';

// Must match MAX_SIMPLIFY_LENGTH on the server (BOOLEAN_LAB_MAX_SIMPLIFY_LENGTH).
const MAX_LENGTH = 2000;
const CACHE_SIZE = 20;
const EXAMPLES = [
  "(a + b)'(a' + c) + ab'c + a'bc",
  "xy + x'z + yz",
  "(a nand b)' + (c ^ d)(c + d')",
  "ab + ab'",
  "a + a'b + b'c",
];
const PHASE_LABEL: Record<SimplifyStep['phase'], string> = {
  definitions: 'DEFINITION',
  negations: 'NEGATIONS',
  reduce: 'REDUCE',
  expand: 'MULTIPLY OUT',
  factor: 'FACTOR',
};
const STOP_LABEL = { time: 'TIME LIMIT', steps: 'STEP LIMIT', size: 'SIZE LIMIT' } as const;

type SimplifyError = { code: ApiErrorCode | 'network_error'; message: string; position?: number; sent: string };

function Highlighted({ text, span }: { text: string; span: [number, number] }) {
  const { before, mid, after } = splitHighlight(text, span);
  return <>{before}<mark>{mid}</mark>{after}</>;
}

function StepCard({ step, before, compact }: { step: SimplifyStep; before: string; compact: boolean }) {
  return (
    <li className="simplify-step drafted-box">
      <div className="step-head">
        <span className="step-no">{String(step.number).padStart(2, '0')}</span>
        <span className="rule-badge" title={step.dual ? `Dual rule: ${step.dual}` : undefined}>{step.rule}</span>
        <b className="rule-name">{step.rule_name.toUpperCase()}</b>
        <span className="step-phase">{PHASE_LABEL[step.phase]}</span>
        {step.direction === 'backward' && <span className="step-flag">READ BACKWARDS</span>}
        {!step.on_sheet && <span className="step-flag hazard-flag">NOT ON YOUR SHEET</span>}
      </div>
      <code className="step-equation">{step.equation}</code>
      <p className="step-explain">{step.explain}</p>
      {step.also.length > 0 && (
        <p className="step-also">ALSO USED: {step.also.map((r) => `${r.id} ${r.name.toUpperCase()}`).join(' · ')}</p>
      )}
      <div className="step-focus"><code>{step.focus_before}</code><span>=</span><code>{step.focus_after}</code></div>
      {!compact && (
        <div className="step-full">
          <span className="micro-label">BEFORE</span>
          <code><Highlighted text={before} span={step.before_span} /></code>
          <span className="micro-label">AFTER</span>
          <code><Highlighted text={step.after} span={step.after_span} /></code>
        </div>
      )}
    </li>
  );
}

function RuleSheet() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ['simplify-rules'],
    queryFn: ({ signal }) => api.simplifyRules(signal),
    staleTime: Infinity,
  });
  if (isLoading) return <p className="micro-label">LOADING RULE SHEET...</p>;
  if (isError || !data) return <p className="micro-label">COULD NOT LOAD THE RULE SHEET</p>;
  return (
    <div className="table-scroll">
      <table className="notation-table">
        <thead><tr><th>ID</th><th>RULE</th><th>EQUATION</th><th>DUAL</th><th>NOTE</th></tr></thead>
        <tbody>{data.map((rule) => (
          <tr key={rule.id}>
            <td>{rule.id}</td><td>{rule.name}</td><td><code>{rule.equation}</code></td>
            <td>{rule.dual || '—'}</td><td>{rule.on_sheet ? '' : rule.note}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function SimplifyView({ presetName, customPreset, labExpression, onOpenLab }: {
  presetName: string;
  customPreset: Preset | null;
  labExpression: string;
  onOpenLab: (expression: string) => void;
}) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<SimplifyResponse | null>(null);
  const [error, setError] = useState<SimplifyError | null>(null);
  const [loading, setLoading] = useState(false);
  const [stale, setStale] = useState(false);
  const [fromCache, setFromCache] = useState(false);
  const [compact, setCompact] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Results already received, so asking for the same thing again costs the server nothing.
  const cacheRef = useRef<Map<string, SimplifyResponse>>(new Map());

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Newlines become spaces one-for-one, so error positions from the server still line up with the text.
  const payloadText = text.replace(/\n/g, ' ');
  const canRun = payloadText.trim().length > 0 && !loading && cooldown <= 0;

  const run = useCallback(async () => {
    if (!canRun) return;
    const custom = customPreset;
    const key = JSON.stringify([payloadText, presetName, custom]);
    const cached = cacheRef.current.get(key);
    if (cached) {
      setResult(cached); setError(null); setStale(false); setFromCache(true);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const data = await api.simplify({
        expression: payloadText,
        preset: custom ? 'universal' : presetName,
        custom_preset: custom,
      }, controller.signal);
      if (controller.signal.aborted) return;
      if (cacheRef.current.size >= CACHE_SIZE) {
        const oldest = cacheRef.current.keys().next().value;
        if (oldest !== undefined) cacheRef.current.delete(oldest);
      }
      cacheRef.current.set(key, data);
      setResult(data); setStale(false); setFromCache(false);
    } catch (caught) {
      if (controller.signal.aborted) return;
      if (caught instanceof ApiClientError) {
        setError({ code: caught.code, message: caught.message, position: caught.position, sent: payloadText });
        if (caught.code === 'rate_limited' || caught.code === 'busy') setCooldown(Math.min(caught.retryAfter ?? 5, 120));
      } else {
        setError({ code: 'network_error', message: 'NO CONNECTION TO DRAFTING SERVER', sent: payloadText });
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [canRun, customPreset, payloadText, presetName]);

  const edit = (value: string) => {
    setText(value.slice(0, MAX_LENGTH));
    if (result) setStale(true);
  };

  const caret = error?.code === 'parse_error' && error.position ? buildErrorCaret(error.sent, error.position) : null;
  const ratio = useMemo(() => (result ? `${result.start_literals} → ${result.result_literals}` : ''), [result]);
  const flash = (message: string) => setToast(message);

  return (
    <section className="simplify-view drafted-box">
      <div className="section-heading"><span>S1</span><h2>SIMPLIFY STEP BY STEP</h2><i /></div>
      <p className="guide-lead">
        Paste a long expression and press SIMPLIFY. Every step uses one rule of the course sheet (P1–P5, T1–T6) and is named.
        Nothing runs while you type.
      </p>

      <div className="simplify-input">
        <textarea
          className="function-input simplify-textarea"
          rows={4}
          value={text}
          maxLength={MAX_LENGTH}
          placeholder="(a + b)'(a' + c) + ab'c + a'bc"
          aria-label="Boolean expression to simplify"
          spellCheck={false}
          onChange={(event) => edit(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void run(); } }}
        />
        <div className="input-meta"><span>NOTATION: {customPreset ? customPreset.name.toUpperCase() : presetName.toUpperCase()} · CTRL+ENTER TO RUN</span><span>{text.length} / {MAX_LENGTH}</span></div>
        <div className="simplify-actions">
          <button className="primary-button plot-button" onClick={() => void run()} disabled={!canRun}>
            {loading ? <><Loader2 size={13} className="spin" /> WORKING...</> : cooldown > 0 ? cooldownLabel(cooldown) : 'SIMPLIFY'} <span>↗</span>
          </button>
          {labExpression.trim() && labExpression !== text && (
            <button className="outline-button" onClick={() => edit(labExpression)}>USE LAB EXPRESSION</button>
          )}
        </div>
        <div className="example-row"><span className="micro-label">EXAMPLES</span>
          {EXAMPLES.map((example) => <button key={example} className="chip" onClick={() => edit(example)}>{example}</button>)}
        </div>
      </div>

      {error && (
        <div className="note drafted-box hazard">
          <div className="error-title"><AlertTriangle size={16} /> {error.code === 'rate_limited' ? 'SLOW DOWN' : error.code === 'busy' ? 'SERVER BUSY' : error.code === 'network_error' ? 'NO CONNECTION' : 'REVISION REQUIRED'}</div>
          {caret && <pre className="caret-display"><code>{caret.expression}{'\n'}{caret.caret}</code></pre>}
          <p>{error.message}</p>
          {cooldown > 0 && <p>THE BUTTON UNLOCKS IN {cooldown} S.</p>}
        </div>
      )}

      {result && (
        <div className={stale ? 'results stale' : 'results'}>
          {stale && <div className="note drafted-box">EXPRESSION CHANGED. PRESS SIMPLIFY TO WORK IT OUT AGAIN.</div>}
          <div className="simplify-summary">
            <div className="stat"><span className="micro-label">VARIABLES</span><b>{result.variables.length ? result.variables.join(' ') : '—'}</b></div>
            <div className="stat"><span className="micro-label">LETTERS WRITTEN</span><b>{ratio}</b></div>
            <div className="stat"><span className="micro-label">STEPS</span><b>{result.step_count}</b></div>
            <div className="stat"><span className="micro-label">CHECK</span><b><Check size={13} /> SAME TRUTH TABLE · {2 ** result.variables.length} ROWS</b></div>
          </div>

          <div className="simplify-result drafted-box">
            <span className="micro-label">RESULT</span>
            <code className="result-expr">F = {result.result}</code>
            <div className="control-actions">
              <button className="outline-button" onClick={async () => { await copyText(result.result); flash('RESULT COPIED'); }}><Copy size={13} /> COPY RESULT</button>
              <button className="outline-button" onClick={async () => { await copyText(stepsToText(result)); flash('WORKING COPIED'); }}><Copy size={13} /> COPY ALL STEPS</button>
              <button className="outline-button" onClick={() => downloadText(stepsToText(result), 'simplification.txt', 'text/plain')}><Download size={13} /> .TXT</button>
              <button className="outline-button" onClick={() => onOpenLab(result.result)}>OPEN IN LAB ↗</button>
            </div>
            <p className="simplify-caveat">SIMPLIFIED WITH THE RULES BELOW, NOT PROVEN MINIMAL. "FEWER LETTERS" IS THE MEASURE USED.{fromCache ? ' · SHOWN FROM THIS SESSION, NO REQUEST SENT.' : ''}</p>
          </div>

          {result.warnings.map((warning) => (
            <div key={warning} className="note drafted-box hazard"><AlertTriangle size={14} /> {warning}{result.stopped ? ` (${STOP_LABEL[result.stopped]})` : ''}</div>
          ))}

          {result.routes.length > 0 && (
            <div className="simplify-routes drafted-box">
              <span className="micro-label">ROUTES TRIED · THE SHORTEST IS SHOWN</span>
              <div className="table-scroll"><table className="notation-table">
                <thead><tr><th>ROUTE</th><th>LETTERS</th><th>STEPS</th><th /></tr></thead>
                <tbody>{result.routes.map((route) => (
                  <tr key={route.name} className={route.chosen ? 'route-chosen' : ''}>
                    <td>{route.name}</td>
                    <td>{route.literals ?? '—'}</td>
                    <td>{route.steps ?? '—'}</td>
                    <td>{route.chosen ? 'SHOWN' : route.status === 'gave_up' ? `SKIPPED (${STOP_LABEL[route.reason ?? 'size']})` : ''}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          )}

          <div className="simplify-steps-head">
            <div className="section-heading"><span>S2</span><h2>THE STEPS</h2><i /></div>
            <button className="outline-button" onClick={() => setCompact((value) => !value)}>{compact ? 'SHOW FULL EXPRESSION' : 'COMPACT VIEW'}</button>
          </div>
          <div className="simplify-start"><span className="micro-label">READ AS</span><code>{result.parsed}</code></div>
          {result.steps.length === 0
            ? <div className="note drafted-box">NOTHING TO SIMPLIFY: NONE OF THE RULES APPLIES TO THIS EXPRESSION.</div>
            : <ol className="simplify-steps">{result.steps.map((step, index) => (
                <StepCard key={step.number} step={step} before={textBeforeStep(result, index)} compact={compact} />
              ))}</ol>}
        </div>
      )}

      <div className="simplify-sheet">
        <button className="outline-button" onClick={() => setSheetOpen((value) => !value)} aria-expanded={sheetOpen}>
          RULE SHEET <ChevronDown size={13} style={{ transform: sheetOpen ? 'rotate(180deg)' : undefined }} />
        </button>
        {sheetOpen && <div className="note drafted-box"><RuleSheet /></div>}
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </section>
  );
}
