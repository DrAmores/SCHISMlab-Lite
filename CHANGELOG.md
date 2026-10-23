# Cambios

Las novedades de cada versión de SCHISMlab Lite, en lenguaje normal. La interfaz las muestra en **Actualizar** cuando
hay una versión nueva.

## 0.5.10 (2026-10-23) — Partículas: batimetría de fondo y barra de tiempo fluida

- Partículas: el fondo del mapa puede ser la variable o la **profundidad**, y se pueden dibujar las **isobatas** encima,
  para ver los efectos topográficos (columnas de Taylor, corrientes guiadas por el fondo).
- Al arrastrar la barra de tiempo un trozo grande (en Partículas y en Mapas y series) solo se dibuja el último instante
  pedido: antes cada posición intermedia mandaba un fotograma, se saturaba la conexión y la página se recargaba
  perdiendo las partículas. Si la página se recarga igualmente, las partículas calculadas se recuperan.

## 0.5.9 (2026-10-23) — Ejecutar en discos de Windows y con Dropbox

- Al volver a ejecutar un caso guardado en un disco de Windows (/mnt/c, /mnt/d) o en Dropbox, archivar la simulación
  anterior podía fallar con «Operation not permitted» (otro usuario de WSL no puede cambiar permisos ni fechas de esos
  ficheros, y Dropbox o una simulación recién detenida impiden renombrar) y la simulación nueva no arrancaba. Ahora el
  archivo copia solo el contenido, y si algo no se puede archivar se avisa y la simulación se lanza igualmente.

## 0.5.8 (2026-10-23) — Visor de la malla: escala de profundidad ajustada

- En Dominio y malla, la capa Profundidad del visor usa el rango de profundidades de la malla (antes iba siempre de 0 al
  máximo): el escalón de 200 a 199 m de la práctica 2 o un monte submarino se distinguen a simple vista.

## 0.5.7 (2026-10-22) — Resultados: isolíneas, nueva disposición de Mapas y series y secciones

- **Isolíneas encima del campo de color** (Estilo del mapa → Isolíneas): la profundidad o cualquier variable, con
  intervalo automático o elegido, junto con las flechas. Sirve, por ejemplo, para ver si la corriente sigue las
  isobatas alrededor de un monte o si las flechas son paralelas a las isolíneas de la elevación.
- **Mapas y series reorganizado** como Partículas: controles en una columna a la izquierda (variable, nivel y Estilo del
  mapa), el mapa a la derecha con play y tiempo encima, y las pestañas Puntos, Secciones y Animación justo debajo del
  mapa. El alto del mapa se ajusta a la forma del dominio.
- **Secciones**: se dibujan con colores vivos y un halo blanco (la segunda salía casi negra y no se veía sobre muchos
  mapas). El ojo ahora muestra u oculta la sección en el mapa; un botón aparte elige qué sección se representa.
- La reproducción del mapa vuelve a enviar solo el campo en cada fotograma (con Plotly 6 se redibujaba la figura entera).

## 0.5.6 (2026-10-22) — Malla idealizada: parámetros de cada fondo explicados

- Al elegir la forma del fondo (plano, pendiente, escalón, canal, plataforma y talud, monte submarino, fórmula) aparece
  debajo su fórmula y qué es cada parámetro, con sus unidades, y los parámetros se rellenan con un ejemplo adaptado
  al tamaño del dominio (p. ej. el monte submarino en el centro, con radio de una décima del dominio).
- Pro: la página Dominio y malla daba error 500 con un fondo idealizado guardado como forma (p. ej. monte submarino).

## 0.5.5 (2026-10-22) — Resultados: pestaña Partículas renovada

- Controles en una columna a la izquierda: **variable y capa del campo de fondo** propias (ya no hay que ir a Mapas y
  series), **instante de suelta**, centro (o clic en el mapa), número, radio, duración y velocidad.
- Un solo mapa grande con el campo, la zona de suelta, las trayectorias y las partículas, con play/pausa y barra de
  tiempo como en Mapas y series. **El campo de fondo se anima junto con las partículas** (antes desaparecía o se quedaba
  quieto).
- Distancia media y máxima recorrida, y descarga de las trayectorias en CSV.

## 0.5.4 (2026-10-22) — Resultados: escalas de espectros y wavelets

- Espectro, espectro rotatorio y wavelet ajustan sus ejes a los periodos y potencias de los datos. Antes las etiquetas
  de las líneas de referencia (inercial, M2, K1…) se colocaban mal en los ejes logarítmicos y estiraban la escala hasta
  10²⁴ h, y los datos quedaban en una esquina. Solo se marcan las referencias que caen dentro de los datos.

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
