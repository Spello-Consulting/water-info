// Chart hover: on a desktop (mouse) browser, snap a tooltip to the nearest
// data point as the pointer moves across the plot. Touch devices never fire
// mousemove, so the chart stays static there.
(function () {
  "use strict";

  document.querySelectorAll("svg.chart .chart-hover").forEach(initChart);

  function initChart(group) {
    const svg = group.ownerSVGElement;
    let points;
    try {
      points = JSON.parse(group.dataset.points || "[]");
    } catch (e) {
      return;
    }
    if (!points.length) return;

    const hit = group.querySelector(".chart-hit");
    const cursor = group.querySelector(".chart-cursor");
    const marker = group.querySelector(".chart-marker");
    const tip = group.querySelector(".chart-tooltip");
    const bg = tip.querySelector(".chart-tooltip-bg");
    const tTime = tip.querySelector(".chart-tooltip-time");
    const tVal = tip.querySelector(".chart-tooltip-val");

    // Plot bounds (SVG user units) come straight from the hit rectangle.
    const px = parseFloat(hit.getAttribute("x"));
    const py = parseFloat(hit.getAttribute("y"));
    const pw = parseFloat(hit.getAttribute("width"));
    const ph = parseFloat(hit.getAttribute("height"));

    const svgPoint = svg.createSVGPoint();

    function toUserX(evt) {
      svgPoint.x = evt.clientX;
      svgPoint.y = evt.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      return svgPoint.matrixTransform(ctm.inverse()).x;
    }

    function nearest(x) {
      let best = points[0];
      let bestDist = Math.abs(best.x - x);
      for (const p of points) {
        const d = Math.abs(p.x - x);
        if (d < bestDist) {
          bestDist = d;
          best = p;
        }
      }
      return best;
    }

    function show(p) {
      cursor.setAttribute("x1", p.x);
      cursor.setAttribute("x2", p.x);
      cursor.style.display = "";
      marker.setAttribute("cx", p.x);
      marker.setAttribute("cy", p.y);
      marker.style.display = "";

      tTime.textContent = p.t;
      tVal.textContent = p.v;
      const pad = 8;
      const w = Math.max(tTime.getComputedTextLength(), tVal.getComputedTextLength()) + pad * 2;
      bg.setAttribute("width", w);

      // Prefer the tooltip to the right of / above the point, flipping to stay
      // inside the plot area.
      let bx = p.x + 12;
      if (bx + w > px + pw) bx = p.x - 12 - w;
      if (bx < px) bx = px;
      let by = p.y - 48;
      if (by < py) by = p.y + 12;
      tip.setAttribute("transform", `translate(${bx}, ${by})`);
      tip.style.display = "";
    }

    function hide() {
      cursor.style.display = "none";
      marker.style.display = "none";
      tip.style.display = "none";
    }

    hit.addEventListener("mousemove", (evt) => {
      const x = toUserX(evt);
      if (x === null) return;
      show(nearest(x));
    });
    hit.addEventListener("mouseleave", hide);
  }
})();
