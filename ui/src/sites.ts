/** Site coordinates accepted by the output evaluators. Unknown content stays unplotted. */
export interface Site {
  lon: number;
  lat: number;
  outline?: number[][];
  additionalOutlines?: number[][][];
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function coordinate(value: unknown): value is number[] {
  return Array.isArray(value) && value.length >= 2 &&
    value.every(n => typeof n === 'number' && Number.isFinite(n)) &&
    Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90;
}

function ring(value: unknown): value is number[][] {
  return Array.isArray(value) && value.length > 2 && value.every(coordinate);
}

export function readSites(output: unknown): Site[] {
  if (typeof output === 'string') {
    try { return readSites(JSON.parse(output)); } catch { return []; }
  }
  const obj = record(output);
  const entries = Array.isArray(output) ? output : obj.sites ?? obj.locations;
  if (!Array.isArray(entries)) return [];

  return entries.flatMap(entry => {
    const site = record(entry);
    const props = record(site.properties);
    const geometry = record(site.geometry ?? site);
    const coords = geometry.coordinates;
    const rings = geometry.type === 'Polygon' && Array.isArray(coords) ? coords :
      geometry.type === 'MultiPolygon' && Array.isArray(coords) ? coords.flat() : [];
    const outlines = rings.filter(ring);
    const outline = outlines[0];
    const point = coordinate(entry) ? entry :
      geometry.type === 'Point' && coordinate(coords) ? coords : null;
    const lon = props.lon ?? props.lng ?? props.longitude ?? site.lon ?? site.lng ??
      site.longitude ?? point?.[0] ??
      (outline ? outline.reduce((n,p) => n+p[0],0)/outline.length : undefined);
    const lat = props.lat ?? props.latitude ?? site.lat ?? site.latitude ?? point?.[1] ??
      (outline ? outline.reduce((n,p) => n+p[1],0)/outline.length : undefined);
    if (typeof lon !== 'number' || typeof lat !== 'number' ||
        !Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon)>180 || Math.abs(lat)>90) {
      return [];
    }
    return [{
      lon, lat,
      ...(outline ? {outline} : {}),
      ...(outlines.length > 1 ? {additionalOutlines:outlines.slice(1)} : {}),
    }];
  });
}
