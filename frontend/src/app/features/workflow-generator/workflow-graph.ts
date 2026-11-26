// Compute the designer graph from workflow definitions and configured step routes.
import type { DesignerStep } from '../../services/workflow-api.service';

export type Port = 'gotoStep' | 'onTrue' | 'onFalse' | 'onError';
export const portLabels: Record<Port, string> = {
  gotoStep: 'Next', onTrue: 'Yes', onFalse: 'No', onError: 'Error',
};

export function transitionId(value: unknown): string {
  const target = value && typeof value === 'object' ? (value as Record<string, unknown>)['gotoStep'] : value;
  return typeof target === 'string' ? target : '';
}

export function stepPorts(step: DesignerStep): Port[] {
  if (step.type === 'condition') return ['onTrue', 'onFalse', 'onError'];
  if (step.type === 'end' || step.type === 'return') return [];
  return ['gotoStep', 'onError'];
}

export function workflowGraph(steps: DesignerStep[]) {
  const destination = new Map(steps.map((step, index) => [step.id, index + 1]));
  const routes = steps.flatMap((step, index) => {
    const next = steps[index + 1]?.id ?? '';
    const fallback = transitionId(step['gotoStep']) || transitionId(step['onSuccess']) || next;
    return stepPorts(step).flatMap(port => {
      const value = step[port];
      const explicit = transitionId(value);
      const error = transitionId(step['onError']);
      const target = port === 'onTrue' ? explicit || transitionId(step['onSuccess']) || fallback
        : port === 'onFalse' ? explicit || transitionId(step['onFailure']) || error || fallback
        : port === 'gotoStep' ? fallback
        : typeof value === 'object' ? explicit : '';
      const to = destination.get(target);
      return to === undefined ? [] : [{ from: index + 1, to, port, implicit: port === 'gotoStep' && !explicit && !step['onSuccess'] }];
    });
  });
  const outgoing = new Map<number, number[]>();
  for (const { from, to } of routes) {
    const neighbors = outgoing.get(from) ?? [];
    neighbors.push(to);
    outgoing.set(from, neighbors);
  }
  const rows: number[][] = [[0]];
  const visited = new Set([0]);
  if (steps.length) {
    rows.push([1]);
    visited.add(1);
    for (let row = 1; row < rows.length; row++) {
      const next: number[] = [];
      for (const node of rows[row]) {
        for (const to of outgoing.get(node) ?? []) {
          if (visited.has(to)) continue;
          visited.add(to);
          next.push(to);
        }
      }
      if (next.length) rows.push(next);
    }
  }
  for (let node = 1; node <= steps.length; node++) {
    if (!visited.has(node)) rows.push([node]);
  }
  const width = Math.max(330, ...rows.map(row => row.length * 218 + 84));
  const positions = new Map<number, { x: number; y: number }>();
  rows.forEach((row, depth) => row.forEach((node, column) => {
    positions.set(node, { x: width / 2 + (column - (row.length - 1) / 2) * 218, y: 34 + depth * 130 });
  }));
  const edges = (steps.length ? [{ from: 0, to: 1, port: 'gotoStep' as Port, implicit: true }, ...routes] : []).map(route => {
    const a = positions.get(route.from)!;
    const b = positions.get(route.to)!;
    const sourceX = a.x + (route.port === 'onTrue' ? -30 : route.port === 'onFalse' ? 30 : route.port === 'onError' ? 58 : 0);
    const sourceY = a.y + 52;
    const destY = b.y - 5;
    const midY = (sourceY + destY) / 2;
    const side = Math.max(a.x, b.x) + 105;
    const forward = b.y > a.y;
    return {
      ...route,
      path: forward ? `M${sourceX},${sourceY} V${midY} H${b.x} V${destY}`
        : `M${sourceX},${sourceY} v18 H${side} V${destY - 14} H${b.x} V${destY}`,
      x: forward ? (sourceX + b.x) / 2 : side,
      y: forward ? midY - 7 : destY - 20,
    };
  });
  return { width, height: rows.length * 130, start: positions.get(0)!, nodes: steps.map((step, index) => ({
    step, index, ...positions.get(index + 1)!,
  })), edges };
}
