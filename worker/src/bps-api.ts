import registry from "../../src/bps_operations.json";
import { readPublicText } from "./http";

type Parameter = { name: string; in: string; required?: boolean; schema: { type?: string; enum?: unknown[]; pattern?: string; minimum?: number; maximum?: number; minLength?: number; maxLength?: number } };
type Operation = { path: string; summary: string; group: string; credential: string; parameters: Parameter[] };
export const operations = registry.operations as Record<string, Operation>;

export function credential(headers: Headers, fallback = "", service = "bps"): string {
  let key = service === "sdgs" ? headers.get("X-BPS-SDGS-Token") : null;
  if (service !== 'sdgs') key = key ?? headers.get("X-BPS-API-Key");
  const auth = headers.get("Authorization");
  if (key === null && auth !== null) {
    if (!/^Bearer /i.test(auth)) throw new Error("Gunakan Authorization: Bearer API_KEY_BPS.");
    key = auth.slice(7);
  }
  key = key ?? fallback;
  if (!/^[A-Za-z0-9._~+\/=-]{8,512}$/.test(key)) throw new Error("API key belum tersedia atau format tidak valid. Gunakan header X-BPS-API-Key atau Authorization: Bearer.");
  return key;
}

export function endpointCatalog(operation = "", query = "") {
  if (operation) {
    if (!Object.hasOwn(operations, operation)) return {ok:false,error:'unknown_operation',message:'Nama operasi tidak dikenal. Gunakan nama persis dari valid_operations.',operation,valid_operations:Object.keys(operations).sort(),suggestions:Object.keys(operations).filter(name=>name.toLowerCase().includes(operation.toLowerCase())).slice(0,5)};
    return { ok:true, operation, ...operations[operation], source: registry.source };
  }
  const list = Object.entries(operations).filter(([name, op]) => `${name} ${op.summary} ${op.group}`.toLowerCase().includes(query.toLowerCase()))
    .map(([operation, op]) => ({ operation, summary: op.summary, group: op.group, credential: op.credential }));
  return { ok:true, operations: list, total: list.length, source: registry.source };
}

export function buildRequest(operation: string, parameters: Record<string, unknown>, key: string) {
  if (!Object.hasOwn(operations, operation) || !parameters || typeof parameters !== "object" || Array.isArray(parameters)) throw new Error("Operasi atau parameter tidak valid.");
  const spec = operations[operation];
  const known = new Map(spec.parameters.map(param => [param.name, param]));
  if (Object.keys(parameters).some(name => !known.has(name))) throw new Error("Parameter tidak didukung untuk operasi ini.");
  let path = spec.path;
  const query = new URLSearchParams();
  for (const [name, param] of known) {
    if (!Object.hasOwn(parameters, name)) { if (param.required) throw new Error(`Parameter wajib: ${name}`); continue; }
    const value = parameters[name], schema = param.schema;
    if ((typeof value !== "string" && (typeof value !== "number" || !Number.isSafeInteger(value))) || String(value).length > 500) throw new Error(`Parameter tidak valid: ${name}`);
    if (schema.type === "integer" && typeof value !== "number" || schema.type === "string" && typeof value !== "string") throw new Error(`Tipe parameter tidak valid: ${name}`);
    if (schema.enum && !schema.enum.includes(value)) throw new Error(`Pilihan parameter tidak valid: ${name}`);
    if (typeof value === "number" && (value < (schema.minimum ?? value) || value > (schema.maximum ?? value))) throw new Error(`Parameter di luar rentang: ${name}`);
    if (typeof value === "string" && (value.length < (schema.minLength ?? 0) || value.length > (schema.maxLength ?? 500) || schema.pattern && !new RegExp(schema.pattern).test(value))) throw new Error(`Format parameter tidak valid: ${name}`);
    if (param.in === "path") {
      if (!String(value) || [".", ".."].includes(String(value)) || /[/\\?#%\x00-\x1f]/.test(String(value))) throw new Error(`Segmen path tidak valid: ${name}`);
      path = path.replace(`{${name}}`, encodeURIComponent(String(value)));
    } else query.set(name, String(value));
  }
  if (operation === "listDomains" && parameters.type === "kabbyprov" && !parameters.prov) throw new Error("Parameter prov wajib untuk type kabbyprov.");
  const suffix = query.size ? `?${query}` : "";
  return { url: `https://webapi.bps.go.id${path.replace("{key}", encodeURIComponent(key))}${suffix}`,
    publicUrl: `https://webapi.bps.go.id${path.replace("{key}", "***")}${suffix}`, headers: (spec.credential === "sdgs" ? { Token: key } : {}) as Record<string, string> };
}

export async function executeBps(operation: string, parameters: Record<string, unknown>, headers: Headers, fallback = "") {
  if (!Object.hasOwn(operations, operation)) return endpointCatalog(operation);
  const key = credential(headers, operations[operation].credential === 'sdgs' ? '' : fallback, operations[operation].credential);
  const request = buildRequest(operation, parameters, key);
  try {
    const text = await readPublicText(request.url, 5 * 1024 * 1024, 30_000, request.headers);
    const safe = text.replaceAll(key, "***").replaceAll(encodeURIComponent(key), "***").replace(/(\/key\/)[^/?#\s"<>]+/gi, "$1***");
    const data = JSON.parse(safe);
    return { ok: Boolean(data && typeof data === "object" && !data.errors && String(data.status).toLowerCase() !== "error" && ("data" in data || "datacontent" in data)), operation, url: request.publicUrl, data };
  } catch { return { ok: false, error: "upstream_error", message: "BPS tidak dapat diakses atau respons melebihi batas; periksa key dan parameter." }; }
}
