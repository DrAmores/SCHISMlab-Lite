# Identidad visual

![SCHISMlab](img/logo.svg){ width=420 }

SCHISMlab tiene una identidad propia, independiente de la UIB y del IMEDEA. Está pensada en la tradición del
modernismo suizo: rejilla, aire, una tipografía bien dibujada y muy poco color, para que el color lo pongan los datos.

## Símbolo

Nueve puntos que crecen hacia una esquina, el mayor en turquesa: la **resolución variable** de la malla no estructurada,
que es lo que distingue a SCHISM. Es abstracto, se reconoce a cualquier tamaño y no se parece a ninguna ola.
Ficheros en `schismlab/gui/brand/`: `symbol.svg` (símbolo), `logo.svg` (símbolo y palabra), `icon.svg` (icono de aplicación,
cuadrado redondeado grafito), `favicon.svg` (versión mínima de cuatro puntos), `social.svg` (imagen 1280×640 para redes y README).

La palabra se escribe siempre **SCHISM** en negrita y *lab* en regular turquesa: el modelo y lo que añadimos.

## Colores

| Uso | Nombre | Hex |
|---|---|---|
| Primario: texto, cabecera, botones principales | grafito | `#2b2b2b` |
| Acento: lo activo, lo seleccionado, «lab» | turquesa | `#0e9aa7` |
| Fondo | blanco | `#ffffff` |
| Paneles y fondos secundarios | gris | `#efefef` |
| Texto secundario | gris texto | `#6a6a6a` |
| Avisos y errores | naranja | `#d8542b` |
| Estados correctos | verde | `#2f8f5b` |
| Modo oscuro: fondo y paneles | oscuro | `#1c1c1c` / `#262626` |

Series de las figuras (puntos, secciones, espectros): turquesa, grafito, naranja, violeta `#7a4fb8`, verde `#4d8f2f`,
ocre `#b8860b`, frambuesa `#b5536a`, azul `#4a7fb0`. Los mapas de los campos mantienen escalas científicas (Viridis,
RdBu, RdYlBu, deep) porque allí el color es información, no marca.

## Tipografía

- **Space Grotesk** para títulos y texto (títulos en 700, texto en 400).
- **JetBrains Mono** para todo lo que se mide o se escribe: números, unidades, ejes, YAML y registros.

Ambas son libres (Google Fonts); la interfaz las carga en línea y, sin red, cae en Helvetica/Arial y Menlo/Consolas.

## Reglas de uso

- Fondo blanco (o grafito oscuro en modo oscuro); nunca degradados ni sombras de color.
- El turquesa señala una sola cosa por pantalla: el paso activo, el acordeón abierto, la acción principal.
- Un solo peso de línea para bordes (2 px grafito en cabecera y barras fijas; 3 px turquesa en el elemento activo).
- Los números van en monoespaciada y con formato por idioma (9 139 m; 0,41 en español, 0.41 en inglés).
- El símbolo no se deforma ni se recolorea; en oscuro los puntos pasan a claro y el grande sigue turquesa.
