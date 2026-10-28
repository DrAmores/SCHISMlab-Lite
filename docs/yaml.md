# El fichero del caso (YAML): referencia completa

Todo lo que hace SCHISMlab se describe en un fichero YAML. La interfaz lo escribe por ti, pero es reproducible,
se puede versionar y editar a mano. Aquí están **todas las claves que lee el código** (`schismlab/setup.py`,
`schismlab/mesh/build.py` y la interfaz), por secciones. Las claves que no se escriben toman el valor por defecto.

## Expresiones

Donde se admite un número también se admite una expresión numpy, entre comillas, con las variables `x`, `y`
(metros desde la esquina suroeste del dominio), `lon`, `lat` (grados), `z` (cota, negativa hacia abajo), `depth`
(= `h`, profundidad positiva) y `t` (días desde el inicio, solo en forzamientos). Funciones: `sin cos tan exp log
sqrt tanh sinh cosh abs where minimum maximum clip sign arctan deg2rad heaviside gauss(r, sigma)`, constantes `pi`,
`e`. Ejemplos: `"where(z > -50, 20, 12)"`, `"0.5*gauss(sqrt((x-30e3)**2 + (y-25e3)**2), 10e3)"`. Las expresiones se
validan antes de evaluarse: solo aritmética, comparaciones y esas funciones (nada de atributos, índices ni llamadas
a otras cosas), de modo que un caso importado de otra persona no puede ejecutar código.

## Cabecera

```yaml
name: mi_caso          # nombre del caso: carpeta de trabajo <carpeta del YAML>/<name>/ (sin espacios ni acentos)
workdir: ruta          # opcional: carpeta de trabajo distinta (absoluta o relativa al YAML)
build: hydro           # compilación de SCHISM que se usa: hydro | wwm | <nombre de variante> (ver Instalación)
```

## mesh (dominio y malla)

```yaml
mesh:
  generator: idealized               # dominio idealizado: rectángulo en metros
  rebuild: false                     # true: regenerar la malla en el setup aunque exista hgrid.gr3
  # --- dominio idealizado
  Lx: 300000                         # lados del dominio (m)
  Ly: 120000
  dx: 3000                           # tamaño de celda (m)
  bathymetry: 100                    # profundidad uniforme (m) o {kind: flat|slope|step|channel|shelf|seamount, ...}
  # fórmula libre (m, positiva hacia abajo): x, y en m desde la esquina SW
  bathymetry: {kind: expression, formula: "100 - 80*exp(-((x-150e3)**2 + (y-60e3)**2)/(2*20e3**2))"}
  open_sides: [S, N]                 # lados abiertos (W, E, S, N); el resto son paredes
  side_types: {S: radiation, N: radiation}   # tipo de cada lado abierto: forced (defecto) | radiation (Flather)
```

## vertical

```yaml
vertical: {type: 2d}
vertical: {type: sigma, nvrt: 20, h_c: 10, theta_b: 0, theta_f: 4}
vertical: {type: sz, nsigma: 20, zlevels: [-2500, -1500, -1000, -700, -500, -300], h_c: 10, theta_b: 0.5, theta_f: 5}
```

## time

```yaml
time: {start: 2020-01-01, days: 2, dt: 60, ramp_days: 0.5}     # start admite hora: 2020-01-01T06:30
```

## physics

```yaml
physics:
  baroclinic: false      # true: T y S activas (solo con malla vertical 3D; en 2D se ejecuta barotropo)
  transport: false       # true: transporta T y S sin que afecten a la densidad
  turbulence: 3          # itur: 0 ninguno | 3 k-kl (GLS) | 5 k-ε (GLS); en 2D se ignora
  coriolis: f-plane      # f-plane | beta | none
  shapiro: 1             # filtro de Shapiro (ishapiro)
  shapiro0: 0.1          # fuerza del filtro (0–0.5): 0.1 por defecto en dominios idealizados, 0.5 en mallas reales
  indvel: 0              # método de velocidad (0 = recomendado)
  ihorcon: 0             # viscosidad horizontal (0 | 1 | 2)
  hvis_coef0: 0.025      # coeficiente de viscosidad horizontal (con ihorcon)
  diffmin: 1.e-6         # difusividad/viscosidad vertical mínima y máxima (m²/s)
  diffmax: 1.0
  hmin_man: 1.0          # profundidad mínima para la fricción de Manning
  thetai: 0.6            # implicitud
reference: {lon0: 2.0, lat0: 40.0}    # referencia para Coriolis (lat0: plano f; borde sur del plano β)
```

## initial

```yaml
initial:
  elevation: 0                       # número o expresión (x, y, lon, lat)
  temperature: "where(z > -50, 20, 12)"
  salinity: 36
  velocity: {u: 0.2, v: 0}           # opcional: velocidad inicial (este, norte); escribe hotstart.nc
  hotstart: false                    # true: forzar hotstart.nc aunque T y S no dependan de z
  recipe: {temperature: {mode: layers, v_top: 20, v_bot: 12, depth: 50, slope_m: 20, axis: x, pos: 0.5, width_km: 10}}
  #   receta de la interfaz (modos: constant, front, layers, toplayer, gauss, gradient, expr); regenera la expresión
```

## forcing

```yaml
forcing:
  wind: {u: 10, v: 0, ramp_days: 0.5, dt_hours: 1, formula: 1}       # uniforme o expresiones (x, y, lon, lat, t)
  #   formula: 1 = Hwang (2018), -1 = Pond & Pichard (iwind_form); la salida windStress es tau/rho_w (m²/s²): Pa = ×1000
  wind: {stress: {x: 0.1, y: 0}, formula: 1}                           # esfuerzo (Pa) en vez de viento: se invierte Cd(|W|)
  #   para que SCHISM aplique exactamente ese tau (números o expresiones; rampa 0 por defecto)
```

## boundaries

```yaml
boundaries:                          # un bloque común a todos los contornos abiertos, o una lista (uno por contorno)
  elevation: none                    # none | 0 | número | {tides: ...} | {series: [[h, m], ...]} | {tsunami: {...}}
  elevation: {tides: {source: idealized, constituents: [M2], amplitude: 0.5, phase: 0}}
  elevation: {tsunami: {shape: n_wave, height: 3, period_min: 20, arrival_h: 0.5, waves: 3}}   # solitary | n_wave | leading_depression
  tidal_potential: true
  velocity: none                     # none | número (caudal constante, <0 entra) | flather | {tides: {...}}
  temperature: ic                    # ic (valor inicial) | none | número ; salinity igual
  min_depth: 10                      # profundidad mínima impuesta en los nodos de contorno abierto (m)
  sponge: null                       # null | {width_km: 40, relax_uv: 0.01, relax_elev: 0}
  #   relax_* en 1/s; la interfaz lo pide como tiempo de relajación: relax_uv = 1/(minutos·60)
```

## stations y output

```yaml
stations: [{name: centro, x: 50000, y: 50000}]           # x, y en m desde la esquina SW
output:
  variables: [elevation, depthAverageVel, horizontalVel, temperature, salinity, zCoordinates]   # catálogo iof_hydro completo
  interval_minutes: 60               # intervalo de los mapas
  stack_hours: 24                    # horas por fichero netCDF
  hotstart_hours: 0                  # hotstart periódico (0 = no); SCHISM los escribe por proceso (hotstart_NNNN_paso.nc):
                                     #   para reanudar hay que combinarlos con combine_hotstart7 (utilidad de SCHISM, no incluida aún)
  station_interval_minutes: 10       # intervalo de las estaciones
  station_variables: [elev, T, S, u, v, w]   # también airP, windx, windy
```

## scenario, friction, param, namelists

```yaml
friction: {manning: 0.025}           # Manning constante
param: {dt: 30}                      # sobreescrituras directas de param.nml (manda sobre todo lo anterior)
namelists: {param.nml: {...}, sediment.nml: {...}}   # lo que guarda «Parámetros avanzados»
```



