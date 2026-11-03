export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false, closed = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (quoted) {
      if (c === '"') {
        if (source[i + 1] === '"') { cell += '"'; i++; }
        else { quoted = false; closed = true; }
      } else cell += c;
    } else if (c === "," || c === "\n" || c === "\r") {
      row.push(cell); cell = ""; closed = false;
      if (c !== ",") {
        if (c === "\r" && source[i + 1] === "\n") i++;
        if (row.some(Boolean) || row.length > 1) rows.push(row);
        row = [];
      }
    } else if (c === '"' && !cell && !closed) quoted = true;
    else {
      if (closed || c === '"') throw new Error("CSV tidak valid.");
      cell += c;
    }
  }
  if (quoted) throw new Error("Kutip CSV tidak lengkap.");
  if (cell || closed || row.length) { row.push(cell); rows.push(row); }
  if (rows.some(row => row.length !== rows[0].length)) throw new Error("Jumlah kolom CSV tidak konsisten.");
  return rows;
}

export function encodeCsv(rows: string[][]): string {
  return rows.map(row => row.map(cell => /[",\r\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell).join(",")).join("\n");
}

export function observationMetadata(rows: string[][]) {
  const header = (rows[0] || []).map(s => s.trim().toLowerCase());
  const yearCol = header.findIndex(s => ["tahun", "thn", "year", "th", "periode", "waktu"].includes(s));
  const years = yearCol < 0 ? [] : rows.slice(1).flatMap(row => row[yearCol]?.match(/\b(?:19|20)\d{2}\b/g) || []).sort();
  const unitCol = header.findIndex(s => ["satuan", "unit"].includes(s));
  const labelCol = header.indexOf("indikator");
  const units = [...new Set(rows.slice(1).map(row => row[unitCol]).filter(Boolean))];
  const labels = [...new Set(rows.slice(1).map(row => row[labelCol]).filter(Boolean))];
  return {
    observationStart: years[0] || "", observationEnd: years.at(-1) || "",
    unit: units.length === 1 ? units[0] : "", indicator: labels.length === 1 ? labels[0] : "",
  };
}
