import type { AnalyzeResponse, Bit, TruthTableRow } from '../api/types';

export function truthTableToTSV(result: AnalyzeResponse): string {
  const headers = ['#', ...result.truth_table.variables, 'F'];
  const rows = result.truth_table.rows.map((row) => [row.index, ...row.inputs, row.output]);
  return [headers.join('\t'), ...rows.map((row) => row.join('\t'))].join('\n');
}

export function truthTableToCSV(result: AnalyzeResponse): string {
  const headers = ['#', ...result.truth_table.variables, 'F'];
  const rows = result.truth_table.rows.map((row) => [row.index, ...row.inputs, row.output]);
  return [headers.join(','), ...rows.map((row) => row.join(','))].join('\n');
}

export function bitsToBinary(inputs: Bit[]): string { return inputs.join(''); }
export function findTruthRow(rows: TruthTableRow[], index: number): TruthTableRow | undefined {
  return rows.find((row) => row.index === index);
}
export function downloadText(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
export async function copyText(content: string): Promise<void> {
  await navigator.clipboard.writeText(content);
}
