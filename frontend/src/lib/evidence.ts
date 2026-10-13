// Parser offsets count Unicode code points, rather than JavaScript UTF-16 units.
export function evidenceParts(text: string, start: number, end: number) {
  const points = Array.from(text);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > points.length) return null;
  return { before: points.slice(0, start).join(""), quote: points.slice(start, end).join(""), after: points.slice(end).join("") };
}
