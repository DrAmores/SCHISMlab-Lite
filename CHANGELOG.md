# Cambios

Las novedades de cada versión de SCHISMlab Lite, en lenguaje normal. La interfaz las muestra en **Actualizar** cuando
hay una versión nueva.

## 0.7.5 (2026-10-27) — La fecha de t1/t2 siempre se aplica

- Promediar entre t1 y t2: la media usa siempre la fecha escrita en el campo. A veces la última tecla no llegaba al
  programa, sobre todo con el panel Perfil y hodógrafa abierto, y la media seguía con la ventana anterior aunque el
  campo mostrara la nueva. Lo mismo en el campo Instante. Además, Intro y luego salir del campo ya no recalculan la
  media dos veces.
- Escala fija de `elevation`: ya no baja hasta 0 por el reposo inicial y la rampa. En un caso con nivel medio de 0.46 m
  va de 0.36 a 0.56 m, como el mapa del instante.
- Barras de color: la marca central es 0 también en el mapa de diferencias de Comparar y en los Hovmöller (antes
  «−4.44e-17»).
- Vista previa de las condiciones iniciales (Física): el eje dice «distancia desde el extremo oeste (O) (km)», como en
  Secciones, y empieza en 0.

## 0.7.4 (2026-10-27) — Arreglos pedidos al repetir las prácticas

Lecturas que daban números distintos:

- Perfil y hodógrafa: en el transporte y en el ajuste, «hasta 0» (o vacío) es la superficie libre. Con η > 0 el nivel
  de superficie quedaba fuera de la integral (P6: Tx 3.51 en vez de 4.08 m²/s). «Desde» vacío es el fondo.
- Secciones: el número de puntos depende de la longitud del corte y de la malla (dos por elemento en el tramo más fino,
  de 120 a 2000). Con 120 fijos, un pulso de 20 km en una sección de 1000 km salía con 1.75 m en vez de 1.87 m (P3).
- Con **Restar** un valor, las lecturas dan dónde la curva cruza ese valor (con Restar = 16 en la temperatura, el frente).
- Con el mapa en **profundidad de isosuperficie**, *Solo en el nivel del mapa* dibuja h(x) de la isosuperficie a lo
  largo del corte, con el ajuste y la integral (P4: ajuste de ln(H − h)).
- Unidades: las series de `transport` en Puntos van en m²/s y la integral de una velocidad en m²/s (antes «m/s·m»).
- La variable de Secciones sigue a la del mapa hasta que se elige otra a mano (antes se quedaba en la del principio).
- Batimetrías analíticas (talud, escalón, canal, plataforma, monte) en dominios en lon/lat: x, y, x0… en metros desde
  la esquina SW, como en las expresiones (antes recibían grados y la plataforma quedaba a h_shelf en todo el dominio).

Presentación:

- Espectro: las líneas de marea solo se dibujan si el caso tiene marea (tapaban la inercial).
- Comparar: el mapa de diferencias tiene el rojo en los valores positivos, como el de elevación.
- Física: en 2D no se muestra el cierre turbulento (SCHISMlab pone itur = 0).
- Barras de color: el 0 sale como 0 (no −2.2e-17) y la densidad con decimales. La escala de `elevation` solo se centra
  en 0 si hay valores a los dos lados (con un nivel medio de 0.46 m el mapa salía de un color).
- Curvas casi constantes (u en un canal sin rotación) se dibujan planas: el eje no amplía diferencias de 1e-6.
- Isolíneas de las secciones sin las de los extremos: ya no salen líneas verticales en el agua fría casi uniforme.
- Series: la media de cada serie en la ventana va en una tabla bajo la figura (en el título se cortaba) y hay 16
  colores distintos para los puntos.
- Selectores «Componente del mapa», «Componente en las series» y «Componente en la sección».
- Eje de las secciones: «distancia desde el extremo oeste (O)»; la nota gris del Hovmöller ya no tapa el eje.
- Perfil y hodógrafa: la hodógrafa no dibuja el nivel del fondo (velocidad nula) y, si la viscosidad cambia en el tramo
  del ajuste (k-kl), avisa de que De y Az suponen A_z constante.
- Partículas en casos 2D: empiezan sobre `depthAverageVel`.
- Ayuda: sentido del signo de 1/α, `shapiro0` = 0.5 para frentes estrechos (P6), periodos largos con registros
  cortos, filtrar la lista de Comparar escribiendo; la de sigma-z dice que h_s es el nivel z menos profundo.

## 0.7.3 (2026-10-26) — Viscosidad constante en Física

- Física → Modelo: con el cierre turbulento «ninguno» aparecen la viscosidad vertical A_z (`dfv0`) y la difusividad
  vertical K_z (`dfh0`), sin tener que ir a Parámetros avanzados. Junto con el filtro de Shapiro (`shapiro0`) y el
  cierre turbulento (ninguno, k-kl o k-ε) permiten elegir desde la interfaz el caso base de cada práctica (por ejemplo,
  P6 con A_z constante o con k-kl y `shapiro0` = 0.5).

## 0.7.2 (2026-10-26)

- La función de corriente indica en el selector que solo vale en cuencas cerradas (sin islas ni contornos abiertos).

## 0.7.1 (2026-10-26) — Secciones en el nivel del mapa

- Secciones: **Solo en el nivel del mapa** dibuja una variable 3D en la capa (o la profundidad fija) del mapa como una
  curva a lo largo del corte, con el ajuste y la integral: por ejemplo, v en superficie a lo largo de la sección.
- La función de corriente se calcula mucho más deprisa en simulaciones largas; la exportación a CSV y el espectro
  admiten las variables derivadas.

## 0.7.0 (2026-10-26) — Prácticas sin cuaderno: derivadas, promedios, espiral de Ekman y secciones con ajuste

Todo lo que las prácticas P1–P7 pedían hacer con el cuaderno se hace ahora en **Mapas y series**:

- **Variables derivadas** en el selector: vorticidad ζ, ζ/f (con el f del modelo, también en plano β), transporte
  integrado en la vertical (Tx, Ty, m²/s) y función de corriente ψ (Sv).
- **Componentes con signo**: módulo, u (este) o v (norte) en el mapa; u, v, normal y tangencial a la sección en
  Secciones y Hovmöller.
- **Promediar entre t1 y t2**: la media de las salidas entre dos fechas en el mapa, las secciones, el perfil vertical
  y las lecturas; en las series se marca la ventana y se da la media de cada una. El título dice cuántas salidas son.
- **Perfil y hodógrafa** en Puntos: u, v, |v| y viscosidad frente a z; v_E frente a u_E con los ejes a la misma
  escala, restando la velocidad de un nivel o la geostrófica de η, con la espiral teórica opcional. Lecturas
  automáticas: corriente de superficie y su ángulo con el viento, profundidad de inversión, ajuste de ln|v_E| (De y
  Az) y transporte con su ángulo.
- **Secciones de variables 2D** (elevation, depthAverageVel, transport...) como curva, con eje logarítmico, valor de
  referencia, ajuste lineal (α y 1/α) e integral entre dos distancias (en Sv con el transporte).
- Las **series de las estaciones** de variables 3D salen del netCDF en la capa elegida (staout solo en superficie).
- Presentación: las secciones predefinidas van de borde a borde y siempre de oeste a este o de sur a norte, con los
  extremos rotulados; las flechas del mapa son las de la propia variable vectorial (y se dice de qué son); barras de
  color legibles (densidad con decimales, campos constantes sin ruido); el nivel 0 se llama «fondo (velocidad nula)»
  en Mapas y Partículas; una wavelet por punto; estaciones con su nombre y un color por serie; campo de fecha y hora
  para ir a una salida; ejes en metros al comparar casos cartesianos; Hovmöller de isosuperficie en gris donde la
  isoterma no corta la columna; la sección en modo isosuperficie usa la escala de la variable; la Malla actual dice
  que mide la arista media y da la arista más corta (= dx); el espectro rotatorio ya no tiene un punto de más.

## 0.6.3 (2026-10-26) — Prácticas: viscosidad con estado inicial y filtro de Shapiro

- **La viscosidad vertical `dfv0` no actuaba** cuando el caso arranca de un estado inicial completo (`hotstart.nc`, que
  se escribe si T, S o la velocidad dependen de la posición) y no hay cierre turbulento. Ahora sí. Cambian los
  resultados de P1, P4 y P6: en P6 la corriente de superficie ya no se satura a 5 m/s y el transporte de Ekman queda a
  un 4 % del teórico.
- **Filtro de Shapiro más suave por defecto** (`shapiro0` = 0.1 en vez de 0.5): el valor máximo frenaba las corrientes
  junto a las paredes. Los casos guardados sin ese valor también usan 0.1. Se puede cambiar en **Física → Modelo**.

## 0.6.2 (2026-10-24) — Página Parámetros

- Pasar a **Parámetros** daba un error 500 («No such file or directory: …/schismlab/forcing/waves.py»): la página buscaba en un sitio antiguo el código que dice qué parámetros fija
  SCHISMlab. Ya no hace falta.

## 0.6.1 (2026-10-24)

- Sin cambios en SCHISMlab Lite (versión a la par con SCHISMlab Pro, que corrige la compilación con oleaje cuando el
  oleaje está desactivado).

## 0.6.0 (2026-10-23)

- Sin cambios en SCHISMlab Lite (versión a la par con SCHISMlab Pro, que añade los tsunamis por deformación del fondo).

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
