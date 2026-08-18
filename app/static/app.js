// Compteur de caractères sur le formulaire de rédaction.
(function () {
  const textarea = document.getElementById('message');
  const counter = document.getElementById('counter');
  if (!textarea || !counter) return;
  const update = () => {
    const length = textarea.value.length;
    // Limite pratique la plus basse des deux réseaux : la légende Instagram.
    counter.textContent = length + ' caractères' +
      (length > 2200 ? " — au-delà de 2 200, Instagram refusera la légende." : '');
    counter.style.color = length > 2200 ? 'var(--critical)' : '';
  };
  textarea.addEventListener('input', update);
  update();
})();

// Survol des courbes : repère vertical et infobulle sur le relevé le plus proche.
document.querySelectorAll('.chart[data-chart]').forEach(function (figure) {
  let payload;
  try {
    payload = JSON.parse(figure.dataset.chart);
  } catch (error) {
    return;
  }
  const svg = figure.querySelector('svg');
  const hit = figure.querySelector('.hit');
  const crosshair = figure.querySelector('.crosshair');
  const tooltip = figure.querySelector('.tooltip');
  if (!svg || !hit || !tooltip) return;

  const formatTime = function (iso) {
    const date = new Date(iso);
    return date.toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  };

  const move = function (event) {
    const box = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    const clientX = (event.touches ? event.touches[0].clientX : event.clientX);
    const x = (clientX - box.left) / box.width * viewBox.width;

    let nearest = null;
    payload.series.forEach(function (entry) {
      entry.points.forEach(function (point) {
        const distance = Math.abs(point.x - x);
        if (!nearest || distance < nearest.distance) {
          nearest = { distance: distance, x: point.x, time: point.t };
        }
      });
    });
    if (!nearest) return;

    const rows = payload.series.map(function (entry) {
      const point = entry.points.find(function (candidate) {
        return candidate.t === nearest.time;
      });
      if (!point) return '';
      return '<div class="tt-row"><i style="background:' + entry.color + '"></i>' +
        entry.name + ' : <strong>' + point.v.toLocaleString('fr-FR') + '</strong></div>';
    }).join('');
    if (!rows) return;

    tooltip.innerHTML = '<div class="tt-time">' + formatTime(nearest.time) + '</div>' + rows;
    tooltip.hidden = false;
    crosshair.setAttribute('x1', nearest.x);
    crosshair.setAttribute('x2', nearest.x);
    crosshair.style.display = '';

    const ratio = box.width / viewBox.width;
    const left = nearest.x * ratio;
    tooltip.style.left = Math.min(
      Math.max(left - tooltip.offsetWidth / 2, 0),
      Math.max(box.width - tooltip.offsetWidth, 0)
    ) + 'px';
    // Sous le titre et la légende, sans les masquer. Un élément SVG n'expose
    // pas offsetTop : on mesure la position réelle du tracé.
    const figureBox = figure.getBoundingClientRect();
    tooltip.style.top = (box.top - figureBox.top + 6) + 'px';
  };

  const leave = function () {
    tooltip.hidden = true;
    crosshair.style.display = 'none';
  };

  hit.addEventListener('mousemove', move);
  hit.addEventListener('touchmove', move, { passive: true });
  hit.addEventListener('mouseleave', leave);
  hit.addEventListener('touchend', leave);
});
