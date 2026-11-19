import { Component, EventEmitter, OnInit, Output } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SentinelService } from '../../services/Sentinel.service';

/** How your Wi-Fi did over a period, ready to print (assets/engine/report.py). */
@Component({
    selector: 'lib-sentinel-reports',
    templateUrl: './reports.component.html',
    styleUrls: ['../theme.css', './reports.component.css']
})
export class ReportsComponent implements OnInit {
    @Output() open = new EventEmitter<string>();

    data: any = null;
    loading = false;
    days = 7;
    readonly periods = [{ value: 1, label: '24 h' }, { value: 7, label: '7 days' }, { value: 30, label: '30 days' }];
    readonly severities = ['critical', 'high', 'medium', 'low', 'info'];
    readonly severityLabels = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Info', good: 'Good' };
    readonly kindLabels = {
        evil_twin: 'Imitation of your network', my_ap_conflict: 'Two devices, one address',
        my_ap_downgrade: 'Weaker security', my_ap_changed: 'Access point changed',
        my_ap_channel: 'Channel change', deauth_flood: 'Deauthentication burst',
        beacon_flood: 'Forged access points', karma_ap: 'Answers for any network',
    };

    constructor(private sentinel: SentinelService, private snackBar: MatSnackBar) { }

    ngOnInit(): void { this.load(); }

    load(): void {
        this.loading = true;
        this.sentinel.getReport(this.days)
            .then((d) => { this.data = d; })
            .catch((e) => this.snackBar.open(String(e), 'OK', { duration: 5000 }))
            .then(() => { this.loading = false; });
    }

    setDays(days: number): void {
        this.days = days;
        this.load();
    }

    get periodLabel(): string {
        return this.days === 1 ? 'the last 24 hours' : `the last ${this.days} days`;
    }

    get kinds(): { kind: string, count: number }[] {
        const k = (this.data && this.data.alerts && this.data.alerts.by_kind) || {};
        return Object.keys(k).map((kind) => ({ kind, count: k[kind] })).sort((a, b) => b.count - a.count);
    }

    get serious(): number {
        const s = this.data ? this.data.alerts.by_severity : {};
        return (s.critical || 0) + (s.high || 0);
    }

    /** Points of the score line, one per day (SVG coordinates, 0..100 mapped to the height). */
    trendPoints(key: string, width = 560, height = 80): string {
        const t = (this.data && this.data.trend || []).filter((r) => r[key] !== null && r[key] !== undefined);
        if (t.length < 2) { return ''; }
        const step = width / (t.length - 1);
        return t.map((r, i) => `${(i * step).toFixed(1)},${(height - r[key] / 100 * height).toFixed(1)}`).join(' ');
    }

    get trendDays(): number {
        return ((this.data && this.data.trend) || []).length;
    }

    bandLabel(band: string): string {
        return band === '5' ? '5 GHz' : band === '2.4' ? '2.4 GHz' : (band || '');
    }

    best(band: string): any {
        const b = this.data && this.data.channels && this.data.channels.best && this.data.channels.best[band];
        return b && b.observed ? b.best : null;
    }

    yours(band: string): number[] {
        return ((this.data && this.data.channels.yours) || []).filter((c) => c[0] === band).map((c) => c[1]);
    }

    /** Open the report on its own page, in plain black and white, and print it (or save as PDF). */
    print(): void {
        const w = window.open('', '_blank');
        if (!w) {
            this.snackBar.open('The browser blocked the new window. Allow pop-ups for the Pineapple.', 'OK', { duration: 6000 });
            return;
        }
        w.document.open();
        w.document.write(this.printable());
        w.document.close();
        w.focus();
        setTimeout(() => w.print(), 300);
    }

    /** The report as CSV: one table, a "section" column to filter on in a spreadsheet. */
    downloadCsv(): void {
        const d = this.data, out: any[][] = [];
        const head = ['section', 'date', 'network', 'bssid', 'band', 'channel', 'security', 'pmf', 'wps',
            'level', 'severity', 'type', 'description', 'value'];
        const row = (o: any) => out.push(head.map((h) => o[h]));
        const day = (ts: number) => isoTime(ts);
        row({ section: 'summary', date: day(d.generated_at), description: 'period_days', value: d.days });
        row({ section: 'summary', description: 'my_networks_score', value: d.mine.score });
        row({ section: 'summary', description: 'my_networks_marked', value: d.mine.marked });
        row({ section: 'summary', description: 'my_networks_seen', value: d.mine.seen });
        row({ section: 'summary', description: 'neighbourhood_score', value: d.area.score });
        row({ section: 'summary', description: 'neighbourhood_networks', value: d.area.total });
        row({ section: 'summary', description: 'alerts', value: d.alerts.total });
        row({ section: 'summary', description: 'alerts_serious', value: this.serious });
        row({ section: 'summary', description: `deauth_frames_last_${d.deauth.hours}h`, value: d.deauth.count });
        d.trend.forEach((t) => {
            row({ section: 'trend', date: t.day, description: 'my_networks_score', value: t.my_score });
            row({ section: 'trend', date: t.day, description: 'neighbourhood_score', value: t.area_score });
            row({ section: 'trend', date: t.day, description: 'alerts', value: t.alerts });
        });
        d.mine.todo.forEach((t) => row({ section: 'to_change', network: t.networks.join('; '), severity: t.severity,
            description: t.advice }));
        d.mine.networks.forEach((n) => row({ section: 'my_network', network: n.ssid, bssid: n.bssid,
            band: this.bandLabel(n.band), channel: n.channel, security: n.security, pmf: n.pmf || 'none',
            wps: n.wps ? 'on' : 'off', level: n.grade, date: day(n.last_seen) }));
        d.mine.not_seen.forEach((x) => row({ section: 'my_network_not_seen', network: x.ssid, bssid: x.bssid }));
        this.kinds.forEach((k) => row({ section: 'alert_count', type: k.kind, description: this.kindLabels[k.kind] || k.kind,
            value: k.count }));
        d.alerts.top.forEach((a) => row({ section: 'alert', date: day(a.ts), severity: a.severity, type: a.kind,
            description: a.title }));
        ['2.4', '5'].forEach((b) => {
            row({ section: 'channel', band: this.bandLabel(b), channel: this.best(b), description: 'best_now' });
            this.yours(b).forEach((c) => row({ section: 'channel', band: this.bandLabel(b), channel: c, description: 'yours' }));
        });
        const text = [head].concat(out).map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
        this.save(text, 'text/csv', 'csv');
    }

    /** The report as Markdown, to paste in notes or a ticket. */
    downloadMarkdown(): void {
        const d = this.data, m = md;
        const sev = (s: string) => this.severityLabels[s] || s;
        const lines: string[] = [];
        lines.push('# Sentinel: Wi-Fi report', '');
        lines.push(`${this.periodLabel.charAt(0).toUpperCase() + this.periodLabel.slice(1)}, from ${isoTime(d.since)} ` +
            `to ${isoTime(d.generated_at)} (Pineapple's clock).`, '');
        lines.push('| | |', '|---|---|');
        lines.push(`| Your networks | ${orDash(d.mine.score)}/100 (${d.mine.seen} of ${d.mine.marked} seen) |`);
        lines.push(`| Neighbourhood | ${orDash(d.area.score)}/100 (${d.area.total} networks) |`);
        lines.push(`| Alerts | ${d.alerts.total}, ${this.serious} serious |`);
        lines.push(`| Deauthentication frames | ${d.deauth.count} in the last ${d.deauth.hours} h |`, '');
        if (d.trend.length) {
            lines.push('## Trend', '', '| Day | Your networks | Neighbourhood | Alerts |', '|---|---|---|---|');
            d.trend.forEach((t) => lines.push(`| ${t.day} | ${orDash(t.my_score)} | ${orDash(t.area_score)} | ${t.alerts} |`));
            lines.push('');
        }
        lines.push('## What to change', '');
        if (d.mine.todo.length) {
            d.mine.todo.forEach((t) => lines.push(`- **${sev(t.severity)}.** ${m(t.advice)} (${m(t.networks.join(', '))})`));
        } else {
            lines.push('Nothing to change on your networks.');
        }
        lines.push('', '## Your networks', '');
        if (d.mine.networks.length) {
            lines.push('| Network | BSSID | Band | Security | PMF | WPS | Level |', '|---|---|---|---|---|---|---|');
            d.mine.networks.forEach((n) => lines.push(`| ${m(n.ssid || '(hidden name)')} | ${n.bssid} | ` +
                `${this.bandLabel(n.band)}, ch. ${n.channel} | ${m(n.security)} | ${m(n.pmf || 'none')} | ` +
                `${n.wps ? 'on' : 'off'} | ${sev(n.grade)} |`));
        } else {
            lines.push('None of your networks was seen in this period.');
        }
        if (d.mine.not_seen.length) {
            lines.push('', `Not seen in this period: ${m(d.mine.not_seen.map((x) => x.ssid || x.bssid).join(', '))}.`);
        }
        lines.push('', '## Alerts', '');
        if (d.alerts.total) {
            this.kinds.forEach((k) => lines.push(`- ${k.count} × ${this.kindLabels[k.kind] || k.kind}`));
            lines.push('', '| When | Severity | Alert |', '|---|---|---|');
            d.alerts.top.forEach((a) => lines.push(`| ${isoTime(a.ts)} | ${sev(a.severity)} | ${m(a.title)} |`));
        } else {
            lines.push('No alert in this period.');
        }
        lines.push('', '## Channels', '');
        ['2.4', '5'].forEach((b) => lines.push(`- ${this.bandLabel(b)}: best channel now ${orText(this.best(b), 'not known yet')}, ` +
            `yours ${this.yours(b).join(', ') || 'none'}`));
        lines.push('', '_Sentinel only listens. Channels are sampled while hopping: a very short event can be missed._', '');
        this.save(lines.join('\n'), 'text/markdown', 'md');
    }

    private save(text: string, type: string, ext: string): void {
        const blob = new Blob([text], { type: `${type};charset=utf-8` });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `sentinel-report-${isoTime(this.data.generated_at).slice(0, 10)}-${this.days === 1 ? '24h' : this.days + 'd'}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    private printable(): string {
        const d = this.data, e = esc;
        const when = (ts: number) => new Date(ts * 1000).toLocaleString();
        const sev = (s: string) => this.severityLabels[s] || s;
        const rows = (cells: string[][]) => cells.map((c) => `<tr>${c.map((x) => `<td>${x}</td>`).join('')}</tr>`).join('');
        const nets = d.mine.networks.map((n) => [e(n.ssid || '(hidden name)'), e(n.bssid),
            `${e(this.bandLabel(n.band))} ch. ${e(n.channel)}`, e(n.security), e(n.pmf || 'none'), n.wps ? 'on' : 'off', e(sev(n.grade))]);
        const todo = d.mine.todo.map((t) => `<li><b>${e(sev(t.severity))}.</b> ${e(t.advice)} <span class="soft">(${e(t.networks.join(', '))})</span></li>`).join('');
        const alerts = d.alerts.top.map((a) => [e(when(a.ts)), e(sev(a.severity)), e(this.kindLabels[a.kind] || a.kind), e(a.title)]);
        const kinds = this.kinds.map((k) => [e(this.kindLabels[k.kind] || k.kind), String(k.count)]);
        const trend = this.trendPoints('my_score', 600, 90);
        return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Sentinel report</title><style>
            body { font: 13px/1.45 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #111; margin: 28px; }
            h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 15px; margin: 22px 0 6px; border-bottom: 1px solid #999; padding-bottom: 3px; }
            .soft { color: #555; } .big { font-size: 28px; font-weight: 600; }
            table { border-collapse: collapse; width: 100%; } td { border-bottom: 1px solid #ddd; padding: 4px 6px; vertical-align: top; }
            .figs { display: flex; gap: 40px; margin: 10px 0; } ul { padding-left: 18px; } li { margin: 3px 0; }
            svg { display: block; margin-top: 6px; } @page { margin: 14mm; }
        </style></head><body>
            <h1>Sentinel: Wi-Fi report</h1>
            <div class="soft">${e(this.periodLabel.charAt(0).toUpperCase() + this.periodLabel.slice(1))}, from ${e(when(d.since))} to ${e(when(d.generated_at))}. Times are on the Pineapple's clock.</div>
            <div class="figs">
                <div><div class="big">${orDash(d.mine.score)}/100</div><div class="soft">your networks (${d.mine.seen} of ${d.mine.marked} seen)</div></div>
                <div><div class="big">${orDash(d.area.score)}/100</div><div class="soft">neighbourhood, ${d.area.total} networks</div></div>
                <div><div class="big">${d.alerts.total}</div><div class="soft">alerts, ${this.serious} serious</div></div>
                <div><div class="big">${d.deauth.count}</div><div class="soft">deauthentication frames, last ${d.deauth.hours} h</div></div>
            </div>
            ${trend ? `<div class="soft">Your networks' score, one point per day, from ${e(d.trend[0].day)} to ${e(d.trend[d.trend.length - 1].day)} (0 to 100)</div>
                <svg width="600" height="92" viewBox="0 -1 600 92"><line x1="0" y1="0" x2="600" y2="0" stroke="#ccc" stroke-dasharray="3 4"/>
                <line x1="0" y1="45" x2="600" y2="45" stroke="#ccc" stroke-dasharray="3 4"/><line x1="0" y1="90" x2="600" y2="90" stroke="#999"/>
                <polyline points="${trend}" fill="none" stroke="#111" stroke-width="1.5"/></svg>` : ''}
            <h2>What to change</h2>
            ${todo ? `<ul>${todo}</ul>` : '<p>Nothing to change on your networks.</p>'}
            <h2>Your networks</h2>
            ${nets.length ? `<table><tr class="soft"><td>Network</td><td>BSSID</td><td>Band</td><td>Security</td><td>PMF</td><td>WPS</td><td>Level</td></tr>${rows(nets)}</table>` : '<p>None of your networks was seen in this period.</p>'}
            ${d.mine.not_seen.length ? `<p class="soft">Not seen in this period: ${e(d.mine.not_seen.map((x) => x.ssid || x.bssid).join(', '))}.</p>` : ''}
            <h2>Alerts</h2>
            ${kinds.length ? `<table>${rows(kinds)}</table><p class="soft">The most serious:</p><table>${rows(alerts)}</table>` : '<p>No alert in this period.</p>'}
            <h2>Channels</h2>
            <p>2.4 GHz: best channel ${e(orText(this.best('2.4'), 'not known yet'))}, yours ${e(this.yours('2.4').join(', ') || 'none')}.
               5 GHz: best channel ${e(orText(this.best('5'), 'not known yet'))}, yours ${e(this.yours('5').join(', ') || 'none')}.</p>
            <p class="soft">Sentinel only listens. Channels are sampled while hopping: a very short event can be missed.</p>
        </body></html>`;
    }
}

/** Local date and time, YYYY-MM-DD HH:MM (the Pineapple's clock, as given). */
function isoTime(ts: number): string {
    const d = new Date(ts * 1000), p = (n: number) => ('0' + n).slice(-2);
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * One CSV cell. Network names come from anyone in radio range: a name starting with = + - @
 * (or a tab / carriage return) would run as a formula in a spreadsheet, so it gets a leading quote.
 */
function csvCell(value: any): string {
    let s = value === null || value === undefined ? '' : String(value);
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(s)) {
        s = "'" + s;
    }
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

/** Text inside Markdown: no table break, no formatting, no link or HTML from a network name. */
function md(value: any): string {
    return String(value === null || value === undefined ? '' : value)
        .replace(/[\r\n]+/g, ' ')
        .replace(/([\\`*_{}\[\]()#+!|<>~])/g, '\\$1');
}

function orText(value: any, text: string): any {
    return value === null || value === undefined ? text : value;
}

function orDash(value: any): any {
    return orText(value, '–');
}

function esc(value: any): string {
    return String(value === null || value === undefined ? '' : value)
        .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
