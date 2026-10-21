<p align="center"><img src="docs/img/logo_lite.svg" alt="SCHISMlab Lite" width="460"></p>

**SCHISMlab Lite** es un entorno docente para hacer una simulación completa con el modelo oceánico
[SCHISM](https://ccrm.vims.edu/schismweb/) desde cero, sin escribir código: dominio y malla, física, forzamientos,
salidas, ejecución y análisis de resultados. Es la edición para las prácticas de *Oceanografía Física* de la
Universitat de les Illes Balears: dominios idealizados en metros (cuencas, canales, taludes, montes submarinos),
2D o 3D, barotrópicos o baroclinos, con viento por fórmula o esfuerzo, mareas idealizadas, ondas de tsunami y
contornos de radiación.

## Instalar

```bash
git clone https://github.com/DrAmores/SCHISMlab-Lite
cd SCHISMlab-Lite
bash install/install.sh          # Linux, mac, WSL2   (Windows: install\install.ps1)
pixi run schismlab gui           # abre la interfaz en el navegador
```

El instalador crea el entorno con [pixi](https://pixi.sh), descarga SCHISM precompilado (o lo compila la primera vez)
y ejecuta un caso de prueba. Los detalles están en `docs/instalacion.md` y en el botón **Ayuda** de la interfaz.

## Usar

La interfaz guía en siete pasos: Dominio y malla, Física, Forzamientos y contornos, Salidas, Parámetros avanzados,
Ejecutar y Resultados (mapas, series, secciones, Hovmöller, espectros y wavelets, partículas, comparación de casos e
informe). Desde la terminal:

```bash
pixi run schismlab setup caso.yaml      # prepara los ficheros de SCHISM
pixi run schismlab run caso.yaml        # ejecuta en tu ordenador
```

Las salidas se leen en Python con `schismlab.analysis.open_run(carpeta)`, que devuelve un Dataset de xarray.

## Actualizar

El botón **Actualizar** de la interfaz descarga las versiones nuevas de este repositorio (`git pull`) y reinicia.

## Créditos

Ángel Amores (UIB/IMEDEA). SCHISM es software del Virginia Institute of Marine Science (licencia Apache 2.0).
