# Cambios

Las novedades de cada versión de SCHISMlab Lite, en lenguaje normal. La interfaz las muestra en **Actualizar** cuando
hay una versión nueva.

## 0.4.1 (2026-10-21) — las prácticas, enteras desde la interfaz

- **Caudal en los contornos**: en Forzamientos → Mareas y nivel, «Velocidad en los contornos forzados» admite un
  caudal constante en m³/s (negativo: entra). La práctica de Taylor-Proudman ya no necesita partir de un YAML.
- **Viento**: la rampa (días) y el paso de la serie (h) se pueden cambiar en Atmósfera; antes la rampa no se veía y el
  paso volvía a 1 h al guardar.
- **Malla vertical**: campo theta_b en sigma y sigma-z. La vista previa y «Ver malla vertical» usan el mismo valor que
  la simulación (antes la vista previa de sigma-z suponía theta_b = 0 y se guardaba 0,5).
- **Espectro**: en los dominios cartesianos se dibuja la línea del periodo inercial con la latitud de referencia
  (plano f) o la latitud local (plano β).
- **Cuaderno**: open_run guarda dónde está la simulación y las funciones que necesitan la malla vertical
  (isosuperficie, secciones, profundidad fija, transporte en 3D) la toman de la propia simulación si no se guardó
  zCoordinates.

## 0.4.0 (2026-10-21) — primera versión de SCHISMlab Lite

- Edición para las prácticas de Oceanografía Física: dominios idealizados en metros, 2D y 3D (sigma y sigma-z),
  baroclino o barotrópico, Coriolis en plano f o β, condiciones iniciales por fórmula, viento uniforme, por fórmula o
  como esfuerzo, mareas idealizadas, tsunami, series de nivel y contornos de radiación.
- Resultados: mapas y series, secciones y Hovmöller, espectro y wavelet, partículas, comparación de casos e informe.
