"""Rendu des courbes en SVG, généré côté serveur (aucune librairie externe).

Palette et règles issues du guide de dataviz : deux séries maximum par courbe
(Facebook, Instagram), traits fins, grille discrète, légende systématique dès
deux séries et valeur finale étiquetée directement sur la courbe.
"""
import html
import json
from datetime import datetime

# Emplacements catégoriels 1 et 2, validés en clair comme en sombre.
SERIES_COLORS = ['var(--series-1)', 'var(--series-2)']
PLATFORM_SLOT = {'facebook': 0, 'instagram': 1}


def _nice_ceiling(value):
    """Arrondit le haut de l'axe à une graduation lisible."""
    if value <= 5:
        return 5
    magnitude = 10 ** (len(str(int(value))) - 1)
    for factor in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        candidate = magnitude * factor
        if candidate >= value:
            return int(candidate)
    return int(magnitude * 10)


def _format_tick(iso, span_days):
    moment = datetime.fromisoformat(iso)
    return moment.strftime('%d/%m') if span_days >= 2 else moment.strftime('%d/%m %Hh')


def line_chart(title, series, width=340, height=200):
    """Trace une courbe multi-séries.

    `series` : liste de dicts {name, platform, points:[(iso, valeur)]}.
    Renvoie un fragment HTML prêt à insérer.
    """
    series = [s for s in series if len(s['points']) >= 1]
    if not series:
        return _empty_chart(title)

    pad_left, pad_right, pad_top, pad_bottom = 38, 46, 14, 26
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    stamps = sorted({point[0] for s in series for point in s['points']})
    x_positions = {}
    if len(stamps) == 1:
        x_positions[stamps[0]] = pad_left + plot_w / 2
        span_days = 0
    else:
        first = datetime.fromisoformat(stamps[0])
        last = datetime.fromisoformat(stamps[-1])
        total = max((last - first).total_seconds(), 1)
        span_days = total / 86400
        for stamp in stamps:
            offset = (datetime.fromisoformat(stamp) - first).total_seconds()
            x_positions[stamp] = pad_left + plot_w * (offset / total)

    top = _nice_ceiling(max((v for s in series for _, v in s['points']), default=0))

    def y_of(value):
        return pad_top + plot_h - (plot_h * (value / top) if top else 0)

    parts = []

    # Grille et axe des ordonnées : volontairement discrets.
    for step in range(5):
        value = top * step / 4
        y = y_of(value)
        parts.append(
            f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" '
            f'x2="{pad_left + plot_w}" y2="{y:.1f}" />'
        )
        parts.append(
            f'<text class="tick" x="{pad_left - 8}" y="{y + 4:.1f}" '
            f'text-anchor="end">{_short(value)}</text>'
        )

    # Axe des abscisses : premier, milieu et dernier relevé seulement.
    tick_stamps = [stamps[0]] if len(stamps) == 1 else \
        [stamps[0], stamps[len(stamps) // 2], stamps[-1]]
    for stamp in dict.fromkeys(tick_stamps):
        x = x_positions[stamp]
        anchor = 'start' if stamp == stamps[0] and len(stamps) > 1 else \
            ('end' if stamp == stamps[-1] and len(stamps) > 1 else 'middle')
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{height - 8}" '
            f'text-anchor="{anchor}">{_format_tick(stamp, span_days)}</text>'
        )

    tooltip_payload = []
    for index, entry in enumerate(series):
        color = SERIES_COLORS[PLATFORM_SLOT.get(entry.get('platform'), index) % 2]
        points = sorted(entry['points'])
        coords = [(x_positions[stamp], y_of(value)) for stamp, value in points]
        if len(coords) > 1:
            path = ' '.join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}'
                            for i, (x, y) in enumerate(coords))
            parts.append(f'<path class="line" d="{path}" stroke="{color}" />')
        # Marqueur sur le dernier relevé, cerclé de la couleur de fond.
        last_x, last_y = coords[-1]
        parts.append(
            f'<circle class="dot" cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.5" '
            f'fill="{color}" />'
        )
        # Étiquette directe : la valeur du jour, en encre de texte.
        parts.append(
            f'<text class="value-label" x="{last_x + 10:.1f}" y="{last_y + 4:.1f}">'
            f'{_short(points[-1][1])}</text>'
        )
        tooltip_payload.append({
            'name': entry['name'],
            'color': color,
            'points': [{'x': round(x_positions[s], 1), 'v': v, 't': s} for s, v in points],
        })

    legend = ''
    if len(series) > 1:
        chips = ''.join(
            f'<span class="legend-item"><i style="background:'
            f'{SERIES_COLORS[PLATFORM_SLOT.get(e.get("platform"), i) % 2]}"></i>'
            f'{html.escape(e["name"])}</span>'
            for i, e in enumerate(series)
        )
        legend = f'<div class="legend">{chips}</div>'

    payload = html.escape(json.dumps({
        'series': tooltip_payload,
        'plot': {'left': pad_left, 'right': pad_left + plot_w,
                 'top': pad_top, 'bottom': pad_top + plot_h},
    }), quote=True)

    return (
        f'<figure class="chart" data-chart="{payload}">'
        f'<figcaption>{html.escape(title)}</figcaption>{legend}'
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(title)}" preserveAspectRatio="xMidYMid meet">'
        f'{"".join(parts)}'
        f'<line class="crosshair" y1="{pad_top}" y2="{pad_top + plot_h}" '
        f'x1="0" x2="0" style="display:none" />'
        f'<rect class="hit" x="{pad_left}" y="{pad_top}" width="{plot_w}" '
        f'height="{plot_h}" fill="transparent" />'
        f'</svg><div class="tooltip" hidden></div></figure>'
    )


def _empty_chart(title):
    return (
        f'<figure class="chart chart-empty"><figcaption>{html.escape(title)}</figcaption>'
        f'<p class="muted">Pas encore de relevé. Les chiffres arrivent après le '
        f'premier rafraîchissement.</p></figure>'
    )


def _short(value):
    value = float(value or 0)
    if value >= 10000:
        return f'{value / 1000:.0f}k'
    if value >= 1000:
        return f'{value / 1000:.1f}k'.replace('.0k', 'k')
    return f'{value:.0f}'
