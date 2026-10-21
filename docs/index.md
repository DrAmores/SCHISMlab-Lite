# SCHISMlab Lite

![SCHISMlab Lite](img/logo_lite.svg){ width=420 }

**SCHISMlab Lite** es un entorno docente para hacer una simulación completa con el modelo oceánico
[SCHISM](https://ccrm.vims.edu/schismweb/) desde cero: mallar, forzar, ejecutar y analizar, sin escribir código.
Es la edición de las prácticas de *Oceanografía Física* de la Universitat de les Illes Balears.

## Qué hace

| Paso | Qué obtienes |
|---|---|
| **Malla** | Dominios idealizados en metros: cuenca, canal, talud, plataforma, monte submarino o un fondo por fórmula; cada lado puede ser pared, contorno forzado o de radiación. |
| **Modelo** | 2D o 3D (sigma, sigma-z), barotrópico o baroclino, Coriolis en plano f o β, condiciones iniciales por fórmula (capas, frentes, perfiles). |
| **Forzamientos** | Viento uniforme o por fórmula, esfuerzo del viento en Pa, mareas idealizadas, ondas de tsunami y series de nivel en los contornos. |
| **Ejecutar** | En tu ordenador (Windows con WSL2, Linux o mac). |
| **Salidas** | Variables de SCHISM, frecuencia, pilas y estaciones elegidas en el mapa. |
| **Analizar** | Mapas con flechas, series en puntos, secciones, Hovmöller, animaciones y MP4; espectros y wavelets; partículas; comparación de casos; informe HTML; cuaderno con `open_run`. |

## Empezar

```bash
git clone https://github.com/DrAmores/SCHISMlab-Lite
cd SCHISMlab-Lite
bash install/install.sh          # Linux, mac, WSL2   (Windows: install\install.ps1)
pixi run schismlab gui           # abre la interfaz en el navegador
```
