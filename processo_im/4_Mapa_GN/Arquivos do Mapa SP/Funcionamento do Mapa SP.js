const COMGAS_BOUNDS = L.latLngBounds(
  [-24.00813, -46.82625],
  [-23.35658, -46.3651]
);

const networkMap = L.map("networkMap", {
  zoomControl: false,
  minZoom: 9,
  maxZoom: 20,
  maxBounds: COMGAS_BOUNDS.pad(0.35),
  maxBoundsViscosity: 0.85
});

L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
  minZoom: 9,
  maxZoom: 20,
  attribution: "Tiles &copy; Esri"
}).addTo(networkMap);

L.tileLayer.wms("https://wms.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wms", {
  layers: "geoportal:rede_comgas",
  styles: "",
  format: "image/png",
  transparent: true,
  version: "1.1.1",
  minZoom: 9,
  maxZoom: 20,
  updateWhenIdle: true,
  updateWhenZooming: false,
  keepBuffer: 4,
  attribution: "GeoSampa / COMGÁS"
}).addTo(networkMap);

networkMap.fitBounds(COMGAS_BOUNDS);

document.getElementById("networkClose").addEventListener("click", () => { window.location.href = "index.html?v=20260807"; });
