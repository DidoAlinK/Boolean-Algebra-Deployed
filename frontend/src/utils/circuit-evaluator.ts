import type { Bit, Circuit, CircuitNode } from '../api/types';

export type InputValues = Record<string, Bit>;
export interface CircuitEvaluation { values: Map<string, Bit>; output: Bit }

export function evaluateCircuit(circuit: Circuit, inputValues: InputValues): CircuitEvaluation {
  const values = new Map<string, Bit>();

  for (const node of circuit.nodes) {
    let value: Bit;
    switch (node.kind) {
      case 'input':
        value = inputValues[node.label] ?? 0;
        break;
      case 'const':
        value = Number(node.label) as Bit;
        break;
      case 'output': {
        const sourceId = node.inputs[0];
        if (!sourceId) throw new Error(`Output node ${node.id} has no input.`);
        const sourceValue = values.get(sourceId);
        if (sourceValue === undefined) throw new Error(`Missing source value: ${sourceId}`);
        value = sourceValue;
        break;
      }
      case 'gate': {
        if (!node.table || node.table.length === 0) throw new Error(`Gate ${node.id} has no truth table.`);
        const inputs = node.inputs.map((id) => {
          const inputValue = values.get(id);
          if (inputValue === undefined) throw new Error(`Gate ${node.id} references unavailable node ${id}.`);
          return inputValue;
        });
        if (inputs.length === 0) throw new Error(`Gate ${node.id} has no inputs.`);
        if (node.table.length === 2) {
          value = node.table[inputs[0]!]!;
        } else {
          let accumulator = inputs[0]!;
          for (const next of inputs.slice(1)) {
            const index = (accumulator << 1) | next;
            const result = node.table[index];
            if (result === undefined) throw new Error(`Invalid truth table index ${index} in gate ${node.id}.`);
            accumulator = result;
          }
          value = accumulator as Bit;
        }
        break;
      }
    }
    values.set(node.id, value);
  }

  const output = values.get(circuit.output);
  if (output === undefined) throw new Error(`Circuit output node "${circuit.output}" was not evaluated.`);
  return { values, output };
}

export function getUpstreamCone(circuit: Circuit, targetId: string): Set<string> {
  const nodes = new Map(circuit.nodes.map((node) => [node.id, node]));
  const visited = new Set<string>();
  function visit(id: string): void {
    if (visited.has(id)) return;
    visited.add(id);
    const node: CircuitNode | undefined = nodes.get(id);
    if (!node) return;
    for (const inputId of node.inputs) visit(inputId);
  }
  visit(targetId);
  return visited;
}
