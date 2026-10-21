# Instalación de SCHISMlab Lite

SCHISMlab usa [pixi](https://pixi.sh) para crear un entorno idéntico en todos los sistemas, con los
compiladores Fortran, MPI, NetCDF y Python. SCHISM se descarga precompilado de las releases del repositorio si hay
uno para tu entorno (y se le ajusta la ruta de librerías con `pixi run fix-rpath`); si no, se compila desde las
fuentes la primera vez (10–20 minutos).

## Linux y mac

```bash
git clone https://github.com/DrAmores/SCHISMlab-Lite && cd SCHISMlab-Lite
bash install/install.sh
```

El instalador instala pixi si falta, crea el entorno, compila SCHISM en `~/.schismlab` y ejecuta un caso de
prueba de pocos segundos. La compilación está probada en Ubuntu y en macOS (Apple Silicon) en cada cambio
del repositorio.

## Windows

SCHISM no funciona de forma nativa en Windows. SCHISMlab usa **WSL2** (Ubuntu dentro de Windows):

1. Abre PowerShell **como administrador** y ejecuta:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install\install.ps1
   ```
2. Si WSL2 no estaba instalado, el ordenador pedirá reiniciarse; vuelve a ejecutar el script después.
3. Al terminar, el repositorio queda copiado en Linux (`~/schismlab`) y todo lo demás es igual que en Linux.

!!! tip "Dropbox, OneDrive y discos de Windows"
    No ejecutes SCHISMlab desde una carpeta sincronizada o desde `/mnt/c`: es lento y da errores de bloqueo de
    ficheros. El instalador guarda el entorno y las ejecuciones en el home de Linux.

## Comprobar

```bash
pixi run test        # tests de la librería
pixi run test-run    # caso de prueba con SCHISM (seiche en una cuenca cerrada)
pixi run schismlab gui
```

## Actualizar

Cada instalación es un clon de git. En la interfaz, el botón **Actualizar** de la cabecera comprueba el repositorio
(y se comprueba solo una vez al día), muestra las novedades (`CHANGELOG.md`) y con **Actualizar ahora** descarga los
cambios, reinstala las dependencias si han cambiado, recompila SCHISM si cambió su script y regenera esta ayuda;
después, **Reiniciar la interfaz**. Si has modificado ficheros del repositorio, la actualización se detiene y te lo
dice (guárdalos con `git stash` o `git commit`). Desde la terminal: `git pull --ff-only && pixi install`.

## SCHISMlab Pro

SCHISMlab Lite es la edición de las prácticas. Si te han dado un token de acceso a **SCHISMlab Pro**, pégalo en
**Instalación → SCHISMlab Pro**: la interfaz descarga la extensión en `~/.schismlab/pro`, guarda el token solo en
tu ordenador y se reinicia con la herramienta completa.

