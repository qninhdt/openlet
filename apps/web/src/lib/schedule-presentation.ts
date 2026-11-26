import type { Json } from './agent-api.js';

export function scheduleTiming(spec: Record<string, Json>): string {
  if (typeof spec.at === 'string')
    return new Date(spec.at).toLocaleString([], {
      timeZone: typeof spec.timezone === 'string' ? spec.timezone : undefined,
    });
  if (typeof spec.every_seconds === 'number') {
    for (const [seconds, unit] of [
      [86400, 'day'],
      [3600, 'hour'],
      [60, 'minute'],
      [1, 'second'],
    ] as const)
      if (spec.every_seconds % seconds === 0) {
        const amount = spec.every_seconds / seconds;
        return `Every ${amount} ${unit}${amount === 1 ? '' : 's'}`;
      }
  }
  if (typeof spec.cron === 'string' && spec.cron.trim()) {
    return spec.cron.trim();
  }
  const calendar = spec.calendar;
  if (calendar && typeof calendar === 'object' && !Array.isArray(calendar)) {
    const values = (key: string, fallback: number[]) =>
      Array.isArray(calendar[key]) ? (calendar[key] as number[]) : fallback;
    const days = values('day_of_week', [])
      .map((day) => ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][day])
      .join(', ');
    const times = values('hour', [0])
      .flatMap((hour) =>
        values('minute', [0]).map(
          (minute) => `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
        ),
      )
      .join(', ');
    const dates = ['day_of_month', 'month', 'year', 'second'].flatMap((key) =>
      Array.isArray(calendar[key])
        ? [`${key.replaceAll('_', ' ')}: ${(calendar[key] as number[]).join(', ')}`]
        : [],
    );
    return `${days || 'Daily'} at ${times}${dates.length ? ` · ${dates.join(' · ')}` : ''}`;
  }
  return 'Timing unavailable';
}
