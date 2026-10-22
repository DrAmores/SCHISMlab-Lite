# Cambios

Las novedades de cada versión de SCHISMlab Lite, en lenguaje normal. La interfaz las muestra en **Actualizar** cuando
hay una versión nueva.

## 0.5.3 (2026-10-22) — Resultados: componentes de la velocidad y perfil animado

- Puntos: las series de la velocidad muestran sus **componentes u (hacia el este) y v (hacia el norte)**, con una línea
  en cero, y no solo el módulo. Un selector elige u y v, solo u, solo v o el módulo. Sirve para ver hacia dónde gira
  la corriente (práctica de oscilaciones inerciales).
- El **perfil vertical** del punto se mueve con el tiempo al arrastrar el instante o al reproducir la película, con el
  eje fijo en toda la simulación para que se vea el giro con la profundidad.

## 0.5.2 (2026-10-22) — Resultados: el instante del mapa en las series

- Puntos: en las series temporales, un punto en cada curva y una línea vertical marcan el instante que muestra el mapa,
  y se mueven al arrastrar el tiempo o al reproducir la película (sin redibujar las series).

## 0.5.1 (2026-10-22) — Resultados: reproducción y puntos

- El icono del botón de reproducción (play/pausa) del mapa queda centrado.
- Puntos: si se borra una estación del caso, aparece «Recuperar estaciones borradas» para volver a ponerlas.
- Al reproducir la película del mapa ya no salta a la pestaña Secciones: la sección se sigue actualizando solo si se
  está viendo, y se puede mirar la pestaña Puntos durante la reproducción.

## 0.5.0 (2026-10-22)

- Sin cambios en SCHISMlab Lite (versión a la par con SCHISMlab Pro, que añade los proyectos con varias simulaciones).

## 0.4.3 (2026-10-22)

- Compilación: si cambia el entorno de pixi, SCHISM se compila desde cero (antes podía fallar con «No rule to make
  target pschism»).

## 0.4.2 (2026-10-21)

- Sin cambios en SCHISMlab Lite (versión de mantenimiento, a la par con SCHISMlab Pro).

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
